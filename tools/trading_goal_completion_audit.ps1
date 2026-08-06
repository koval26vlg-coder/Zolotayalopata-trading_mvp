param(
    [switch]$Json,
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [string]$PaperForwardSummaryPath = "",
    [switch]$SkipHeavyGates,
    [switch]$SkipSwarm
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$quickStatusScript = Join-Path $repoRoot "tools\trading_quick_status.ps1"
$strategyAcceptanceGateScript = Join-Path $repoRoot "tools\trading_strategy_acceptance_gate.ps1"
$sweepReversalGateScript = Join-Path $repoRoot "tools\sweep_reversal_acceptance_gate.ps1"
$swarmStatusScript = Join-Path $repoRoot "tools\trading_swarm_status.ps1"
$denseUniversePath = Join-Path $repoRoot "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv"

function Add-Requirement {
    param(
        [System.Collections.Generic.List[object]]$Requirements,
        [string]$Name,
        [string]$Status,
        [string]$Evidence,
        [string]$Action = ""
    )
    $Requirements.Add([ordered]@{
        name = $Name
        status = $Status
        evidence = $Evidence
        action = $Action
    }) | Out-Null
}

function Invoke-JsonScriptAllowFail {
    param([string[]]$Command)

    $output = & $Command[0] @($Command[1..($Command.Count - 1)]) 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String).Trim()
    $payload = $null
    if (-not [string]::IsNullOrWhiteSpace($text)) {
        try {
            $payload = $text | ConvertFrom-Json
        } catch {
            $payload = $null
        }
    }
    return [ordered]@{
        exit_code = $exitCode
        payload = $payload
        raw = $text
    }
}

function Test-BoolTrue {
    param($Value)
    if ($Value -is [bool]) {
        return $Value
    }
    return ([string]$Value).ToLowerInvariant() -eq "true"
}

$requirements = [System.Collections.Generic.List[object]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$nextActions = [System.Collections.Generic.List[string]]::new()

$gate = $null
try {
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -GatePath $GatePath -Json | ConvertFrom-Json
    if ([string]$gate.status -eq "RUNNING") {
        Add-Requirement $requirements "active_run_gate" "fail" "Gate is RUNNING for run_id=$($gate.run_id)." "Only status/ETA checks are allowed."
        $nextActions.Add("wait_for_active_run_or_resume_gate_flow") | Out-Null
    } elseif ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
        Add-Requirement $requirements "active_run_gate" "fail" "Gate is STOPPED_INCOMPLETE for run_id=$($gate.run_id)." "Resume visibly or reject the incomplete dataset."
        $nextActions.Add("visible_resume_or_reject_incomplete_dataset") | Out-Null
    } else {
        Add-Requirement $requirements "active_run_gate" "pass" "Gate is $($gate.status); no active long run is blocking read-only audit."
    }
} catch {
    Add-Requirement $requirements "active_run_gate" "fail" "Gate checker failed: $($_.Exception.Message)" "Fix active-run gate before auditing completion."
    $nextActions.Add("fix_active_run_gate") | Out-Null
}

$quick = $null
try {
    $quick = & pwsh -NoProfile -ExecutionPolicy Bypass -File $quickStatusScript -GatePath $GatePath -SkipSwarm -Json | ConvertFrom-Json
    Add-Requirement $requirements "quick_status" "pass" "Quick status=$($quick.status); would_start=$($quick.would_start); required_input=$($quick.required_user_input)."
    if ([string]$quick.required_user_input -eq "START72H") {
        $nextActions.Add("get_exact_START72H_then_start_visible_dense_ws_collect") | Out-Null
    }
} catch {
    Add-Requirement $requirements "quick_status" "fail" "Quick status failed: $($_.Exception.Message)" "Fix tools/trading_quick_status.ps1."
}

if (Test-Path -LiteralPath $denseUniversePath) {
    $universeRows = @(Import-Csv -LiteralPath $denseUniversePath)
    if ($universeRows.Count -gt 0) {
        Add-Requirement $requirements "non_binance_universe" "pass" "Dense non-Binance universe exists with rows=$($universeRows.Count): $denseUniversePath."
    } else {
        Add-Requirement $requirements "non_binance_universe" "fail" "Dense universe exists but has zero rows: $denseUniversePath." "Rebuild non-Binance dense universe."
        $nextActions.Add("rebuild_dense_non_binance_universe") | Out-Null
    }
} else {
    Add-Requirement $requirements "non_binance_universe" "fail" "Dense universe missing: $denseUniversePath." "Build non-Binance dense universe before data collection."
    $nextActions.Add("build_dense_non_binance_universe") | Out-Null
}

$replayAllowed = $false
if ($gate -and $null -ne $gate.PSObject.Properties["replay_allowed"]) {
    $replayAllowed = [bool]$gate.replay_allowed
}
if ($gate -and [string]$gate.status -eq "READY_FOR_POSTPROCESS" -and $replayAllowed) {
    Add-Requirement $requirements "data_quality_replay_allowed" "pass" "Current postprocess gate has replay_allowed=true."
} else {
    $evidence = if ($gate) { "Current gate status=$($gate.status); replay_allowed=$replayAllowed; next_goal_decision=$($gate.next_goal_decision)." } else { "No gate evidence." }
    Add-Requirement $requirements "data_quality_replay_allowed" "fail" $evidence "Do not run replay/grid on rejected data; collect/prepare an accepted dense dataset first."
    if ($quick -and [string]$quick.required_user_input -eq "START72H") {
        $nextActions.Add("start_visible_72h_dense_ws_collect_after_START72H") | Out-Null
    }
}

$strategyAcceptance = $null
$sweepAcceptance = $null
if ($SkipHeavyGates) {
    Add-Requirement $requirements "strategy_acceptance_gate" "unknown" "Skipped by -SkipHeavyGates." "Run without -SkipHeavyGates before any completion claim."
    Add-Requirement $requirements "sweep_reversal_acceptance_gate" "unknown" "Skipped by -SkipHeavyGates." "Run without -SkipHeavyGates before any completion claim."
} else {
    if (Test-Path -LiteralPath $strategyAcceptanceGateScript) {
        $strategyResult = Invoke-JsonScriptAllowFail -Command @("pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $strategyAcceptanceGateScript, "-Json")
        $strategyAcceptance = $strategyResult.payload
        if ($strategyAcceptance -and (Test-BoolTrue $strategyAcceptance.accepted)) {
            Add-Requirement $requirements "strategy_acceptance_gate" "pass" "Strategy acceptance gate accepted=true."
        } else {
            $reasons = if ($strategyAcceptance -and $strategyAcceptance.reasons) { (@($strategyAcceptance.reasons) -join ",") } else { "exit_code=$($strategyResult.exit_code)" }
            Add-Requirement $requirements "strategy_acceptance_gate" "fail" "Strategy acceptance not accepted: $reasons." "Do not promote to paper-forward/live."
        }
    } else {
        Add-Requirement $requirements "strategy_acceptance_gate" "fail" "Missing $strategyAcceptanceGateScript." "Restore strategy acceptance gate."
    }

    if (Test-Path -LiteralPath $sweepReversalGateScript) {
        $sweepResult = Invoke-JsonScriptAllowFail -Command @("pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $sweepReversalGateScript, "-Json")
        $sweepAcceptance = $sweepResult.payload
        if ($sweepAcceptance -and (Test-BoolTrue $sweepAcceptance.accepted)) {
            Add-Requirement $requirements "sweep_reversal_acceptance_gate" "pass" "Sweep/reversal gate accepted=true."
        } else {
            $reasons = if ($sweepAcceptance -and $sweepAcceptance.reasons) { (@($sweepAcceptance.reasons) -join ",") } else { "exit_code=$($sweepResult.exit_code)" }
            Add-Requirement $requirements "sweep_reversal_acceptance_gate" "fail" "Sweep/reversal gate not accepted: $reasons." "Require independent dense data, replay validation, OOS/walk-forward/stress and economics."
        }
    } else {
        Add-Requirement $requirements "sweep_reversal_acceptance_gate" "fail" "Missing $sweepReversalGateScript." "Restore sweep/reversal gate."
    }
}

$paperAccepted = $false
if ([string]::IsNullOrWhiteSpace($PaperForwardSummaryPath)) {
    Add-Requirement $requirements "paper_forward_gate" "fail" "No paper-forward summary path was provided; no accepted paper-forward evidence exists in this audit." "Only after accepted research gates, run paper-forward in research-only mode."
} elseif (Test-Path -LiteralPath $PaperForwardSummaryPath) {
    try {
        $paper = Get-Content -Raw -LiteralPath $PaperForwardSummaryPath | ConvertFrom-Json
        $paperAccepted = Test-BoolTrue $paper.paper_acceptance.accepted
        if ($paperAccepted -and -not (Test-BoolTrue $paper.live_orders)) {
            Add-Requirement $requirements "paper_forward_gate" "pass" "Paper-forward accepted=true and live_orders is not true."
        } else {
            Add-Requirement $requirements "paper_forward_gate" "fail" "Paper-forward not accepted or unsafe live_orders flag present." "Continue research-only paper-forward validation."
        }
    } catch {
        Add-Requirement $requirements "paper_forward_gate" "fail" "Could not parse paper-forward summary: $($_.Exception.Message)" "Fix paper-forward artifact."
    }
} else {
    Add-Requirement $requirements "paper_forward_gate" "fail" "Paper-forward summary missing: $PaperForwardSummaryPath." "Run paper-forward only after accepted research gates."
}

if ($SkipSwarm) {
    Add-Requirement $requirements "swarm_independent_review" "unknown" "Skipped by -SkipSwarm." "Run swarm status before any completion claim."
} elseif (Test-Path -LiteralPath $swarmStatusScript) {
    try {
        $swarm = & pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json | ConvertFrom-Json
        if ((Test-BoolTrue $swarm.independent_review_available) -and -not (Test-BoolTrue $swarm.swarm_limited)) {
            Add-Requirement $requirements "swarm_independent_review" "pass" "Swarm independent review is available; status=$($swarm.status)."
        } else {
            Add-Requirement $requirements "swarm_independent_review" "fail" "Swarm status=$($swarm.status); swarm_limited=$($swarm.swarm_limited); independent_review_available=$($swarm.independent_review_available)." "Continue manual Codex, then re-check swarm at the next major checkpoint."
        }
    } catch {
        Add-Requirement $requirements "swarm_independent_review" "fail" "Swarm status failed: $($_.Exception.Message)" "Continue manual Codex and retry swarm later."
    }
} else {
    Add-Requirement $requirements "swarm_independent_review" "fail" "Missing $swarmStatusScript." "Restore swarm status script or record manual fallback."
}

Add-Requirement $requirements "safety_boundaries" "pass" "Audit is research-only: would_start=false, no live orders, no API keys, no leverage/margin." ""

$failed = @($requirements | Where-Object { $_.status -eq "fail" })
$unknown = @($requirements | Where-Object { $_.status -eq "unknown" })
$canComplete = ($failed.Count -eq 0 -and $unknown.Count -eq 0)
$status = if ($canComplete) { "COMPLETE_PROVEN" } elseif ($failed.Count -gt 0) { "NOT_COMPLETE" } else { "INCONCLUSIVE" }
if ($nextActions.Count -eq 0) {
    $nextActions.Add("inspect_failed_requirements") | Out-Null
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_goal_completion_audit"
    objective = "find_prove_or_reject_high_winrate_edge_for_non_binance_markets"
    status = $status
    can_mark_goal_complete = $canComplete
    accepted_edge_proven = $canComplete
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    fail_count = $failed.Count
    unknown_count = $unknown.Count
    requirements = @($requirements)
    next_actions = @($nextActions | Select-Object -Unique)
    blocked_actions = @(
        "mark_goal_complete_without_all_requirements_passed",
        "paper_forward_without_accepted_research",
        "replay_grid_on_rejected_data",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "investment_advice_claims"
    )
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "trading_mvp objective completion audit" -ForegroundColor Cyan
Write-Host "Status: $($result.status)"
Write-Host "Can mark goal complete: $($result.can_mark_goal_complete)"
Write-Host "Failures: $($result.fail_count); Unknown: $($result.unknown_count)"
Write-Host ""
foreach ($requirement in $requirements) {
    $prefix = if ($requirement.status -eq "pass") { "[PASS]" } elseif ($requirement.status -eq "unknown") { "[UNKNOWN]" } else { "[FAIL]" }
    Write-Host "$prefix $($requirement.name): $($requirement.evidence)"
    if (-not [string]::IsNullOrWhiteSpace([string]$requirement.action)) {
        Write-Host "       Action: $($requirement.action)"
    }
}
Write-Host ""
Write-Host "Next actions:"
foreach ($action in @($result.next_actions)) {
    Write-Host "  - $action"
}
Write-Host ""
Write-Host "No collector/replay/grid/postprocess/live action was started."

if (-not $canComplete) {
    exit 2
}
exit 0
