param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$nextGoalStep = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$goalStatusScript = Join-Path $repoRoot "tools\trading_goal_status.ps1"
$swarmStatusScript = Join-Path $repoRoot "tools\trading_swarm_status.ps1"
$tradingTestRunnerScript = Join-Path $repoRoot "tools\run_trading_tests.ps1"
$branchSelectorScript = Join-Path $repoRoot "tools\trading_branch_selector.ps1"
$agentsPath = Join-Path $repoRoot "AGENTS.md"
$backlogPath = Join-Path $repoRoot "exports\trading-mvp\analysis\trading_mvp_evidence_to_engineering_backlog_20260617.csv"
$edgePlanPath = Join-Path $repoRoot "docs\plans\2026-06-17-trading-mvp-edge-proof-execution-plan.md"
$edgePlanCsvPath = Join-Path $repoRoot "exports\trading-mvp\analysis\trading_mvp_edge_proof_execution_plan_20260617.csv"
$masterIndexPath = Join-Path $repoRoot "docs\analysis\2026-06-17-anufriev-master-evidence-index.md"
$liveChecklistPath = Join-Path $repoRoot "docs\analysis\live-readiness-checklist.md"
$visibleCollectScript = Join-Path $repoRoot "tools\start_funding_collect_visible.ps1"
$visibleWsCollectScript = Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"
$wsCollectReadinessScript = Join-Path $repoRoot "tools\trading_ws_collect_readiness.ps1"
$collectApprovalContractScript = Join-Path $repoRoot "tools\trading_collect_approval_contract.ps1"
$wsCollectApprovalPacketScript = Join-Path $repoRoot "tools\trading_ws_collect_approval_packet.ps1"
$wsCollectorPy = Join-Path $repoRoot "trading_mvp\src\ws_collector.py"
$visibleWsPreviewShortcut = Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"
$visibleWsConfirmedShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"
$visibleWsPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"
$visibleWsLegacyPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_6h_plan_preview_latest.json"
if ((-not (Test-Path -LiteralPath $visibleWsPlanPreviewLatest)) -and (Test-Path -LiteralPath $visibleWsLegacyPlanPreviewLatest)) {
    $visibleWsPlanPreviewLatest = $visibleWsLegacyPlanPreviewLatest
}
$wsPostprocessShortcut = Join-Path $repoRoot "TRADING_WS_POSTPROCESS_FROM_GATE.cmd"
$wsPostprocessScript = Join-Path $repoRoot "tools\run_ws_postprocess_visible.ps1"
$wsReplayValidationScript = Join-Path $repoRoot "tools\run_ws_replay_validation_visible.ps1"
$dataSufficiencyPlannerScript = Join-Path $repoRoot "tools\trading_data_sufficiency_plan.ps1"
$denseWsCollectPlannerScript = Join-Path $repoRoot "tools\trading_dense_ws_collect_plan.ps1"
$finalReviewScript = Join-Path $repoRoot "tools\run_funding_final_review_visible.ps1"
$strategyAcceptanceGateScript = Join-Path $repoRoot "tools\trading_strategy_acceptance_gate.ps1"
$fundingPostprocessPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json"
$fundingWatchlistScript = Join-Path $repoRoot "tools\funding_candidate_watchlist.ps1"
$fundingWatchlistJson = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json"
$fundingWatchlistReviewScript = Join-Path $repoRoot "tools\funding_watchlist_review.ps1"
$fundingBasisPlanOnlyScript = Join-Path $repoRoot "tools\trading_funding_basis_planonly.ps1"
$structuralBranchPlanOnlyScript = Join-Path $repoRoot "tools\trading_structural_branch_planonly.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$crossVenueFullOutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"
$researchGoalPlanPath = Join-Path $repoRoot "docs\plans\2026-06-15-trading-mvp-research-goal.md"
$feeTierEvidencePath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_account_fee_tiers_current.json"
$currentScorecardPath = Join-Path $repoRoot "exports\trading-mvp\analysis\anufriev_strategy_scorecard_current_20260628.csv"
$currentScorecardName = Split-Path -Leaf $currentScorecardPath
$currentScorecardRequiredArtifacts = @(
    "ws_grid_search_ws_confirmed_research_6h_20260628_103700.json",
    "sweep_reversal_acceptance_ws_confirmed_research_6h_20260628_103700_gatefixed.json",
    "funding_final_review_funding_collect_7d_spotliq_visible_20260617_185732_final_review_20260627_120411.json"
)

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

function Test-TextContains {
    param(
        [string]$Path,
        [string]$Pattern
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    $text = Get-Content -Raw -LiteralPath $Path
    return ($text -match $Pattern)
}

function Read-CsvSafe {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        return @(Import-Csv -LiteralPath $Path)
    }
    return @()
}

function Read-JsonFileOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
}

function Format-CommandNumber {
    param([double]$Value)
    return [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.###}", $Value)
}

function Quote-CommandValue {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function New-WsCollectCommand {
    param(
        [string]$ScriptPath,
        [double]$Hours,
        [int]$MaxPairsPerExchange,
        [string]$UniversePath,
        [switch]$PlanOnly
    )
    $parts = @(
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Quote-CommandValue -Value $ScriptPath),
        "-Hours",
        (Format-CommandNumber -Value $Hours)
    )
    if ($MaxPairsPerExchange -gt 0) {
        $parts += @("-MaxPairsPerExchange", [string]$MaxPairsPerExchange)
    }
    if (-not [string]::IsNullOrWhiteSpace($UniversePath)) {
        $parts += @("-UniversePath", (Quote-CommandValue -Value $UniversePath))
    }
    if ($PlanOnly) {
        $parts += "-PlanOnly"
    } else {
        $parts += "-ConfirmedLongRun"
    }
    return ($parts -join " ")
}

function Resolve-WsCollectCommands {
    param(
        [string]$ScriptPath,
        [string]$PlanPreviewPath
    )
    $hours = 6.0
    $maxPairsPerExchange = 8
    $universePath = ""
    $previewReadError = $null
    $source = "default_6h"
    $previewCommand = New-WsCollectCommand -ScriptPath $ScriptPath -Hours $hours -MaxPairsPerExchange $maxPairsPerExchange -UniversePath $universePath -PlanOnly
    $actualCommand = New-WsCollectCommand -ScriptPath $ScriptPath -Hours $hours -MaxPairsPerExchange $maxPairsPerExchange -UniversePath $universePath

    if (Test-Path -LiteralPath $PlanPreviewPath) {
        try {
            $preview = Get-Content -Raw -LiteralPath $PlanPreviewPath | ConvertFrom-Json
            if ($preview.mode -eq "ws_collect_visible_plan" -and -not [bool]$preview.would_start) {
                if ($null -ne $preview.hours) {
                    $hours = [double]$preview.hours
                }
                if ($null -ne $preview.max_pairs_per_exchange) {
                    $maxPairsPerExchange = [int]$preview.max_pairs_per_exchange
                }
                if (-not [string]::IsNullOrWhiteSpace([string]$preview.universe_path)) {
                    $universePath = [string]$preview.universe_path
                }
                $source = "latest_plan_preview"
                $derivedPreview = New-WsCollectCommand -ScriptPath $ScriptPath -Hours $hours -MaxPairsPerExchange $maxPairsPerExchange -UniversePath $universePath -PlanOnly
                $derivedActual = New-WsCollectCommand -ScriptPath $ScriptPath -Hours $hours -MaxPairsPerExchange $maxPairsPerExchange -UniversePath $universePath
                $previewCommand = $derivedPreview
                $actualCommand = if (-not [string]::IsNullOrWhiteSpace([string]$preview.command_after_explicit_approval)) {
                    [string]$preview.command_after_explicit_approval
                } elseif (-not [string]::IsNullOrWhiteSpace([string]$preview.recommended_command_after_explicit_approval)) {
                    [string]$preview.recommended_command_after_explicit_approval
                } else {
                    $derivedActual
                }
            }
        } catch {
            $source = "default_6h_after_preview_read_error"
            $previewReadError = $_.Exception.Message
        }
    }

    return [ordered]@{
        source = $source
        preview_command = $previewCommand
        command = $actualCommand
        effective_hours = $hours
        effective_max_pairs_per_exchange = $maxPairsPerExchange
        effective_universe_path = $universePath
        plan_preview_path = $PlanPreviewPath
        preview_read_error = $previewReadError
    }
}

$checks = [System.Collections.Generic.List[object]]::new()

$gate = $null
try {
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    $gateStatus = [string]$gate.status
    if ($gateStatus -eq "RUNNING") {
        Add-Check $checks "active_run_gate" "fail" "Gate status is RUNNING for run_id=$($gate.run_id)." "Only status/ETA checks are allowed until the run finishes."
    } elseif ($gateStatus -eq "STOPPED_INCOMPLETE") {
        Add-Check $checks "active_run_gate" "fail" "Gate status is STOPPED_INCOMPLETE for run_id=$($gate.run_id)." "Resume visibly or declare the dataset incomplete before continuing."
    } else {
        Add-Check $checks "active_run_gate" "pass" "Gate status is $gateStatus; completed_cycles=$($gate.completed_cycles)/$($gate.total_cycles); rows=$($gate.rows); errors=$($gate.errors)."
    }
} catch {
    Add-Check $checks "active_run_gate" "fail" "Failed to run gate checker: $($_.Exception.Message)" "Fix tools/check_active_run_gate.ps1 or active-run-gate metadata."
}

$crossVenueFullResult = Read-JsonFileOrNull -Path $crossVenueFullOutputPath
$rawGate = Read-JsonFileOrNull -Path $gatePath
$gateHistory = if ($rawGate) { $rawGate } else { $gate }
if ($gateHistory -and -not $crossVenueFullResult -and $gateHistory.PSObject.Properties.Name -contains "last_cross_venue_dislocation_full_output_path") {
    $crossVenueFullResult = Read-JsonFileOrNull -Path ([string]$gateHistory.last_cross_venue_dislocation_full_output_path)
}
$listingEventReplayResult = $null
if ($gateHistory -and $gateHistory.PSObject.Properties.Name -contains "last_listing_event_replay_output_path") {
    $listingEventReplayResult = Read-JsonFileOrNull -Path ([string]$gateHistory.last_listing_event_replay_output_path)
}
if (-not $listingEventReplayResult -and (Test-Path -LiteralPath $backtestDir)) {
    $latestListingReplay = Get-ChildItem -LiteralPath $backtestDir -Filter "listing_event_replay_planonly_*.json" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestListingReplay) {
        $listingEventReplayResult = Read-JsonFileOrNull -Path $latestListingReplay.FullName
    }
}
$crossVenueFullRejectedByArtifact = [bool](
    $crossVenueFullResult -and
    [string]$crossVenueFullResult.decision -eq "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES"
)
$listingEventReplayRejectedByArtifact = [bool](
    $listingEventReplayResult -and
    [string]$listingEventReplayResult.decision -like "LISTING_EVENT_REPLAY_PLANONLY_REJECTED*"
)

$goalStatus = $null
try {
    $goalStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $goalStatusScript -Json | ConvertFrom-Json
    if ($goalStatus.objective_focus -eq "prove_trading_edge_high_winrate_scheme_in_trading_mvp") {
        Add-Check $checks "objective_focus" "pass" "Goal status focus is $($goalStatus.objective_focus)."
    } else {
        Add-Check $checks "objective_focus" "fail" "Goal status focus is '$($goalStatus.objective_focus)'." "Set focus back to proving trading edge in trading_mvp."
    }
    if ($goalStatus.stale_internal_goal_handling -match "superseded context") {
        Add-Check $checks "stale_internal_goal_guard" "pass" "Goal status treats old channel-analysis goal text as superseded context unless explicitly reopened."
    } else {
        Add-Check $checks "stale_internal_goal_guard" "fail" "Goal status does not clearly handle stale channel-analysis objective text." "Expose stale_internal_goal_handling in tools/trading_goal_status.ps1."
    }
    if ([int]$goalStatus.accepted_trading_strategies -eq 0) {
        Add-Check $checks "accepted_strategy_gate" "pass" "Accepted trading strategies: 0. Live and paper-forward remain blocked."
    } else {
        Add-Check $checks "accepted_strategy_gate" "warn" "Accepted trading strategies: $($goalStatus.accepted_trading_strategies)." "Verify accepted setup has final-review, OOS, walk-forward, stress and paper-forward evidence before any live discussion."
    }
} catch {
    Add-Check $checks "goal_status" "fail" "Failed to run trading_goal_status.ps1: $($_.Exception.Message)" "Fix the goal dashboard before continuing proof work."
}

$swarmStatus = $null
if (-not (Test-Path -LiteralPath $swarmStatusScript)) {
    Add-Check $checks "swarm_status_readback" "fail" "Swarm status script is missing: $swarmStatusScript." "Restore tools/trading_swarm_status.ps1 so swarm_limited cannot be mistaken for approval."
} else {
    try {
        $swarmStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json | ConvertFrom-Json
        if ([string]$swarmStatus.status -eq "SWARM_LIMITED") {
            Add-Check $checks "swarm_status_readback" "pass" "Latest trading_mvp swarm workflow is SWARM_LIMITED; manual Codex fallback is active and this must not be treated as swarm approval."
        } elseif ([string]$swarmStatus.status -eq "SWARM_APPROVED") {
            Add-Check $checks "swarm_status_readback" "pass" "Latest trading_mvp swarm workflow is SWARM_APPROVED."
        } elseif ([string]$swarmStatus.status -eq "SWARM_BLOCKED") {
            Add-Check $checks "swarm_status_readback" "pass" "Latest trading_mvp swarm workflow is SWARM_BLOCKED; branch decisions must respect the blocker."
        } elseif ([string]$swarmStatus.status -eq "NO_TRADING_SWARM_WORKFLOW") {
            Add-Check $checks "swarm_status_readback" "warn" "No trading_mvp swarm workflow was found." "Retry swarm at the next major branch decision, or continue manual Codex only for non-major steps."
        } else {
            Add-Check $checks "swarm_status_readback" "warn" "Latest trading_mvp swarm status is $($swarmStatus.status)." "Do not treat incomplete or pending swarm status as approval."
        }
    } catch {
        Add-Check $checks "swarm_status_readback" "fail" "Failed to read trading swarm status: $($_.Exception.Message)" "Fix tools/trading_swarm_status.ps1 or Aion workflow access before treating swarm state as known."
    }
}

$tradingTestRunnerMarkers = @(
    "run_trading_tests",
    "TRADING_MVP_PYTHON",
    "C:\Program Files\Python313\python.exe",
    "requests",
    "PlanOnly",
    "NO_PYTHON_WITH_REQUESTS",
    "unittest",
    "discover"
)
$tradingTestRunnerMissingMarkers = @(
    $tradingTestRunnerMarkers | Where-Object {
        -not (Test-TextContains -Path $tradingTestRunnerScript -Pattern ([regex]::Escape($_)))
    }
)
if ((Test-Path -LiteralPath $tradingTestRunnerScript) -and $tradingTestRunnerMissingMarkers.Count -eq 0) {
    Add-Check $checks "trading_test_runner" "pass" "Trading test runner exists and selects a Python runtime with requests before running unittest discovery."
} else {
    Add-Check $checks "trading_test_runner" "fail" "Trading test runner is missing or incomplete. Missing markers: $($tradingTestRunnerMissingMarkers -join ', ')." "Restore tools/run_trading_tests.ps1 so tests do not accidentally run on a Python runtime without requests."
}

$backlog = Read-CsvSafe -Path $backlogPath
$scopeFreezeRow = $backlog | Where-Object { $_.backlog_id -eq "P0-003" } | Select-Object -First 1
if ($scopeFreezeRow -and $scopeFreezeRow.decision -eq "freeze_channel_intake" -and $scopeFreezeRow.required_action -match "Do not fetch, retry, monitor, or analyze new YouTube/RSS/transcript") {
    Add-Check $checks "channel_intake_scope" "pass" "Backlog P0-003 freezes new channel intake and keeps existing channel evidence as hypothesis only."
} else {
    Add-Check $checks "channel_intake_scope" "fail" "Backlog P0-003 is missing or does not freeze new channel intake." "Restore channel freeze before doing more goal work."
}

if (Test-TextContains -Path $agentsPath -Pattern "codex-trading-edge-scope-rule") {
    Add-Check $checks "agents_scope_rule" "pass" "AGENTS.md contains codex-trading-edge-scope-rule."
} else {
    Add-Check $checks "agents_scope_rule" "fail" "AGENTS.md does not contain codex-trading-edge-scope-rule." "Add the project-level trading edge scope rule."
}

$currentScorecardIssues = [System.Collections.Generic.List[string]]::new()
if (-not (Test-Path -LiteralPath $currentScorecardPath)) {
    $currentScorecardIssues.Add("missing_current_scorecard:$currentScorecardName") | Out-Null
} else {
    foreach ($artifactName in $currentScorecardRequiredArtifacts) {
        if (-not (Test-TextContains -Path $currentScorecardPath -Pattern ([regex]::Escape($artifactName)))) {
            $currentScorecardIssues.Add("scorecard_missing_artifact:$artifactName") | Out-Null
        }
    }
}
foreach ($controllerScript in @($branchSelectorScript, $goalStatusScript, $strategyAcceptanceGateScript)) {
    $controllerName = Split-Path -Leaf $controllerScript
    if (-not (Test-TextContains -Path $controllerScript -Pattern ([regex]::Escape($currentScorecardName)))) {
        $currentScorecardIssues.Add("controller_missing_current_scorecard:$controllerName") | Out-Null
    }
}
if ($currentScorecardIssues.Count -eq 0) {
    Add-Check $checks "current_scorecard_freshness" "pass" "Current scorecard is $currentScorecardName; branch selector, goal status and acceptance gate are pinned to it; required WS/sweep/funding evidence anchors are present."
} else {
    Add-Check $checks "current_scorecard_freshness" "fail" "Current scorecard freshness failed: $($currentScorecardIssues -join '; ')." "Do not continue proof work until controllers and evidence are pinned to the latest scorecard."
}

$edgePlan = Read-CsvSafe -Path $edgePlanCsvPath
$fundingBlockedBySwarm = (
    (Test-TextContains -Path $researchGoalPlanPath -Pattern "Swarm L1 review 2026-06-27") -and
    (Test-TextContains -Path $researchGoalPlanPath -Pattern "Swarm L2 review 2026-06-27") -and
    (Test-TextContains -Path $researchGoalPlanPath -Pattern "Funding carry remains blocked for paper-forward")
)
$feeTierEvidencePresent = Test-Path -LiteralPath $feeTierEvidencePath
$liquiditySweepRejectedGate = (
    $gate -and
    (
        ([string]$gate.next_goal_decision -eq "LIQUIDITY_SWEEP_REVERSAL_REJECTED_SELECT_NEXT_BRANCH") -or
        ([string]$gate.next_goal_decision -eq "FUNDING_BASIS_CARRY_PLANONLY_CURRENT_COST_NOT_ACCEPTED") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "liquidity_sweep_reversal" -and
            [string]$gate.strategy_branch_status.verdict -eq "rejected"
        )
    )
)
$fundingRejectedBaseFeesGate = (
    $gate -and
    (
        ([string]$gate.next_goal_decision -eq "SELECT_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "funding_basis_carry_structural_planonly" -and
            [string]$gate.strategy_branch_status.verdict -eq "rejected_base_fees"
        )
    )
)
$crossVenueRejectedGate = (
    $gate -and
    (-not ([string]$gate.next_goal_decision -eq "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL")) -and
    (
        $crossVenueFullRejectedByArtifact -or
        ([string]$gate.next_goal_decision -eq "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "cross_venue_spot_dislocation_inventory_rebalance" -and
            [string]$gate.strategy_branch_status.verdict -in @("rejected_base_fees", "rejected_full_scan_base_fees", "rejected_no_net_edge_after_base_fees")
        )
    )
)
$listingEventReplayRejectedGate = (
    $gate -and
    (
        $listingEventReplayRejectedByArtifact -or
        ([string]$gate.next_goal_decision -like "LISTING_EVENT_REPLAY_PLANONLY_REJECTED*") -or
        ([string]$gateHistory.last_listing_event_replay_decision -like "LISTING_EVENT_REPLAY_PLANONLY_REJECTED*") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
            [string]$gate.strategy_branch_status.verdict -eq "replay_planonly_rejected"
        )
    )
)
$listingEventSelectedGate = (
    $gate -and
    (
        ([string]$gate.next_goal_decision -like "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY*") -or
        ([string]$gate.next_goal_decision -like "LISTING_EVENT_CALENDAR*") -or
        ([string]$gate.next_goal_decision -like "LISTING_EVENT_NORMALIZER*") -or
        ([string]$gate.next_goal_decision -like "LISTING_EVENT_HISTORY*") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
            [string]$gate.strategy_branch_status.verdict -in @("planonly_selected_not_tested", "planonly_needs_event_calendar", "planonly_ready_for_event_normalizer", "calendar_partial_needs_delisted_or_nontradable_coverage", "calendar_bias_control_pass_ready_for_normalizer", "normalizer_ready_for_event_replay_planonly", "normalizer_insufficient_overlap_needs_event_ohlcv_history", "normalizer_blocked", "history_planonly_ready_for_visible_collect_preview")
        )
    )
)
$listingEventNormalizerReadyGate = (
    $gate -and
    (
        ([string]$gate.next_goal_decision -eq "LISTING_EVENT_CALENDAR_BIAS_CONTROL_PASS_READY_FOR_NORMALIZER") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
            [string]$gate.strategy_branch_status.verdict -eq "calendar_bias_control_pass_ready_for_normalizer"
        )
    )
)
$listingEventHistoryPlanReadyGate = (
    $gate -and
    (
        ([string]$gate.next_goal_decision -eq "LISTING_EVENT_NORMALIZER_PLANONLY_INSUFFICIENT_OVERLAP_NEEDS_EVENT_OHLCV_HISTORY") -or
        ([string]$gate.next_goal_decision -like "LISTING_EVENT_HISTORY*") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
            [string]$gate.strategy_branch_status.verdict -in @("normalizer_insufficient_overlap_needs_event_ohlcv_history", "history_planonly_ready_for_visible_collect_preview")
        )
    )
)
$listingEventHistoryCollectPreviewAwaitingApprovalGate = (
    $gate -and
    (
        ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
            [string]$gate.strategy_branch_status.verdict -eq "history_collect_preview_ready_awaiting_explicit_approval"
        )
    )
)
$crossVenueStructuralSelectedGate = (
    $gate -and
    (
        (-not $crossVenueRejectedGate) -and
        (
            ([string]$gate.next_goal_decision -eq "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH") -or
            (
                $gate.strategy_branch_status -and
                [string]$gate.strategy_branch_status.branch -eq "cross_venue_spot_dislocation_inventory_rebalance" -and
                [string]$gate.strategy_branch_status.verdict -eq "planonly_selected_not_tested"
            )
        )
    )
)
$primaryStep = $edgePlan | Where-Object { $_.step_id -eq "E3" } | Select-Object -First 1
if ($listingEventReplayRejectedGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "listing_event_drift_reversal replay PlanOnly is rejected on current evidence; next proof step is selecting a new non-HFT structural branch PlanOnly."
} elseif ($listingEventNormalizerReadyGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "Listing calendar passed bias controls; next proof step is read-only listing-event normalizer PlanOnly against the current clean WS slice."
} elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "Listing-event OHLCV history collect preview is ready; next proof step requires explicit user approval before visible public-history collect."
} elseif ($listingEventHistoryPlanReadyGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "Listing-event normalizer blocked replay on current WS slice; next proof step is event OHLCV history PlanOnly / visible collect preview."
} elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "cross_venue_spot_dislocation_inventory_rebalance was rejected by full scan under base fees/buffers; next proof step is listing_event_drift_reversal PlanOnly scaffold."
} elseif ($crossVenueStructuralSelectedGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "cross_venue_spot_dislocation_inventory_rebalance is selected; next proof step is a read-only PlanOnly detector/backtester on existing clean MEXC/Gate data."
} elseif ($fundingRejectedBaseFeesGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "Funding/basis is rejected under base/VIP0/no-volume fees; next proof step is selecting a new non-HFT structural branch through PlanOnly."
} elseif ($liquiditySweepRejectedGate) {
    Add-Check $checks "primary_edge_candidate" "pass" "liquidity_sweep_reversal is rejected by active validation gate; next proof step is funding/basis carry PlanOnly diagnostics or a new structural edge family."
} elseif ($fundingBlockedBySwarm) {
    Add-Check $checks "primary_edge_candidate" "pass" "Funding carry is blocked by Swarm L1/L2; next proof step is fee-tier evidence validation or a different edge family."
} elseif ($primaryStep -and $primaryStep.status -eq "needs_user_confirmation_for_visible_run") {
    Add-Check $checks "primary_edge_candidate" "pass" "E3 is funding/basis carry longer-data proof and requires explicit user confirmation for visible run."
} else {
    Add-Check $checks "primary_edge_candidate" "fail" "E3 is missing or not marked as needs_user_confirmation_for_visible_run." "Restore the edge-proof execution plan before launching any long run."
}

if (
    (Test-Path -LiteralPath $branchSelectorScript) -and
    (Test-TextContains -Path $branchSelectorScript -Pattern "branch_status_override") -and
    (Test-TextContains -Path $branchSelectorScript -Pattern "original_scorecard_next_action") -and
    (Test-TextContains -Path $branchSelectorScript -Pattern "blocked_by_swarm_do_not_run_7d_funding_collect_or_final_review") -and
    (Test-TextContains -Path $branchSelectorScript -Pattern "funding_basis_carry_structural_planonly") -and
    (Test-TextContains -Path $branchSelectorScript -Pattern "postprocess_block_reasons") -and
    (Test-TextContains -Path $branchSelectorScript -Pattern "min_rows_per_cycle")
) {
    Add-Check $checks "branch_selector_funding_block_override" "pass" "Branch selector preserves original scorecard funding next_action, blocks stale funding next_action, and can select funding_basis_carry_structural_planonly after liquidity_sweep_reversal rejection."
} else {
    Add-Check $checks "branch_selector_funding_block_override" "fail" "Branch selector does not expose the funding-block/PlanOnly override markers." "Keep branch selection blocked until tools/trading_branch_selector.ps1 preserves original_scorecard_next_action and routes rejected liquidity_sweep_reversal to funding basis PlanOnly."
}

if ((Test-Path -LiteralPath $liveChecklistPath) -and (Test-TextContains -Path $liveChecklistPath -Pattern "Live trading is blocked")) {
    Add-Check $checks "live_readiness_block" "pass" "Live readiness checklist exists and states live trading is blocked."
} else {
    Add-Check $checks "live_readiness_block" "fail" "Live readiness checklist is missing or does not block live trading." "Keep live/API/leverage blocked until accepted research, paper-forward and explicit approval exist."
}

if (Test-Path -LiteralPath $visibleCollectScript) {
    Add-Check $checks "visible_collect_wrapper" "pass" "Visible 7d funding collect wrapper exists: $visibleCollectScript."
} else {
    Add-Check $checks "visible_collect_wrapper" "fail" "Visible collect wrapper is missing: $visibleCollectScript." "Restore wrapper before any long collect."
}

if ((Test-Path -LiteralPath $visibleCollectScript) -and (Test-TextContains -Path $visibleCollectScript -Pattern "watchlist_path") -and (Test-TextContains -Path $visibleCollectScript -Pattern "WATCHLIST_READY_NOT_TRADEABLE|watchlist_decision")) {
    Add-Check $checks "visible_collect_watchlist_binding" "pass" "Visible collect wrapper binds predeclared funding candidate watchlist into plan/start metadata."
} else {
    Add-Check $checks "visible_collect_watchlist_binding" "fail" "Visible collect wrapper does not expose watchlist binding metadata." "Bind funding_candidate_watchlist_20260617.json before any 7d launch."
}

if (Test-Path -LiteralPath $visibleWsCollectScript) {
    Add-Check $checks "visible_ws_collect_wrapper" "pass" "Visible WS collect wrapper exists: $visibleWsCollectScript."
} else {
    Add-Check $checks "visible_ws_collect_wrapper" "fail" "Visible WS collect wrapper is missing: $visibleWsCollectScript." "Restore wrapper before any WS long collect."
}

if (
    (Test-Path -LiteralPath $visibleWsCollectScript) -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "ConfirmedLongRun") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "PlanOnly") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "postprocess_command_after_ready") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "replay_validation_plan_after_postprocess") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "ExpectedManifestPath")
) {
    Add-Check $checks "visible_ws_collect_postprocess_chain" "pass" "Visible WS collect wrapper requires explicit long-run approval and exposes postprocess plus replay-validation commands with ExpectedManifestPath."
} else {
    Add-Check $checks "visible_ws_collect_postprocess_chain" "fail" "Visible WS collect wrapper does not expose the guarded postprocess/replay-validation chain." "Keep WS collect blocked until PlanOnly/gate metadata includes ManifestPath and ExpectedManifestPath commands."
}

if (
    (Test-Path -LiteralPath $visibleWsCollectScript) -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "EarlyDensityCheckAfterMinutes") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "EarlyDensityMinLinesPerMinute") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "early_density_guard") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "ZeroLineAbortAfterMinutes") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "zero_line_guard") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "SchemaProbeAfterMinutes") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "Test-WsRawSchema") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "schema_probe")
) {
    Add-Check $checks "visible_ws_collect_early_quality_guard" "pass" "Visible WS collect wrapper exposes zero-line, early-density and raw JSONL schema guards before a long WS run can waste the full window."
} else {
    Add-Check $checks "visible_ws_collect_early_quality_guard" "fail" "Visible WS collect wrapper does not expose zero-line/early-density/schema guards." "Add zero-line, early density and raw schema checks to tools/start_ws_collect_visible.ps1 before asking for a confirmed long WS collect."
}

if (
    (Test-Path -LiteralPath $visibleWsCollectScript) -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "self_preflight_guard") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "trading_edge_preflight.ps1") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "READY_FOR_EDGE_PROOF_STEP") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "current_scorecard_freshness") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "Confirmed WS collect refused") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "refuse_confirmed_long_run_before_start")
) {
    Add-Check $checks "visible_ws_collect_self_preflight_guard" "pass" "Visible WS collect wrapper self-runs trading_edge_preflight.ps1 before ConfirmedLongRun and refuses direct starts unless current_scorecard_freshness passes."
} else {
    Add-Check $checks "visible_ws_collect_self_preflight_guard" "fail" "Visible WS collect wrapper can be started without proving current preflight and scorecard freshness." "Require self_preflight_guard in tools/start_ws_collect_visible.ps1 before any confirmed WS collect."
}

if (
    (Test-Path -LiteralPath $visibleWsPreviewShortcut) -and
    (Test-Path -LiteralPath $visibleWsConfirmedShortcut) -and
    (Test-TextContains -Path $visibleWsPreviewShortcut -Pattern "start_ws_collect_visible.ps1") -and
    (Test-TextContains -Path $visibleWsPreviewShortcut -Pattern "-Hours 72") -and
    (Test-TextContains -Path $visibleWsPreviewShortcut -Pattern "no_binance_dense_ws_sweep_20260628.csv") -and
    (Test-TextContains -Path $visibleWsPreviewShortcut -Pattern "-PlanOnly") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "START72H") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "start_ws_collect_visible.ps1") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "trading_collect_approval_contract.ps1") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "trading_ws_collect_approval_packet.ps1") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "-Hours 72") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "no_binance_dense_ws_sweep_20260628.csv") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "-MaxPairsPerExchange 16") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "-ConfirmedLongRun") -and
    (Test-TextContains -Path $visibleWsConfirmedShortcut -Pattern "mexc,gateio")
) {
    Add-Check $checks "visible_ws_collect_shortcut_alignment" "pass" "Dense WS preview/confirmed shortcuts call the guarded visible wrapper; confirmed shortcut requires readiness, approval contract, approval packet, START72H, dense universe and -ConfirmedLongRun."
} else {
    Add-Check $checks "visible_ws_collect_shortcut_alignment" "fail" "Dense WS shortcuts are missing or do not route through the guarded visible wrapper." "Fix TRADING_PREVIEW_DENSE_WS.cmd and TRADING_START_DENSE_WS_CONFIRMED.cmd before asking the user to start a long collect."
}

if (
    (Test-Path -LiteralPath $wsCollectorPy) -and
    (Test-TextContains -Path $wsCollectorPy -Pattern "split_ws_symbols_for_connections") -and
    (Test-TextContains -Path $wsCollectorPy -Pattern "channels_per_symbol") -and
    (Test-TextContains -Path $wsCollectorPy -Pattern "max_symbols_per_connection") -and
    (Test-TextContains -Path $wsCollectorPy -Pattern "chunk_index") -and
    (Test-TextContains -Path $wsCollectorPy -Pattern "chunk_count")
) {
    Add-Check $checks "visible_ws_collect_mexc_chunking" "pass" "WS collector chunks MEXC subscriptions before the 30-channel limit, so dense 16-pair planning can run through multiple safe connections."
} else {
    Add-Check $checks "visible_ws_collect_mexc_chunking" "fail" "WS collector does not prove MEXC channel-limit chunking for dense 72h collect." "Fix trading_mvp/src/ws_collector.py before asking the user to start START72H."
}

if (
    (Test-Path -LiteralPath $visibleWsPlanPreviewLatest) -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "ws_collect_visible_plan") -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT") -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "self_preflight_guard") -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "current_scorecard_freshness") -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "command_after_explicit_approval") -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "ConfirmedLongRun") -and
    (Test-TextContains -Path $visibleWsPlanPreviewLatest -Pattern "replay_validation_plan_after_postprocess")
) {
    Add-Check $checks "visible_ws_collect_plan_preview_freshness" "pass" "Latest visible WS collect preview artifact is current and includes branch decision, self-preflight guard, explicit-approval command and replay-validation plan."
} else {
    Add-Check $checks "visible_ws_collect_plan_preview_freshness" "warn" "Latest visible WS collect preview artifact is missing or stale." "Run the visible WS PlanOnly preview command from trading_next_goal_step.ps1 before asking for explicit collect approval."
}

if (
    (Test-Path -LiteralPath $wsCollectReadinessScript) -and
    ((Test-TextContains -Path $wsCollectReadinessScript -Pattern "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION") -or (Test-TextContains -Path $wsCollectReadinessScript -Pattern "READY_FOR_VISIBLE_WS_COLLECT_APPROVAL_PACKET")) -and
    (Test-TextContains -Path $wsCollectReadinessScript -Pattern "requires_explicit_user_approval_for_actual_collect") -and
    (Test-TextContains -Path $wsCollectReadinessScript -Pattern "stale_6h_confirmed_route") -and
    (Test-TextContains -Path $wsCollectReadinessScript -Pattern "plan_preview_alignment")
) {
    Add-Check $checks "visible_ws_collect_readiness_verifier" "pass" "Visible WS collect readiness verifier exists and checks 72h plan alignment, explicit approval, stale 6h routes and non-starting readiness."
} else {
    Add-Check $checks "visible_ws_collect_readiness_verifier" "fail" "Visible WS collect readiness verifier is missing or incomplete." "Restore tools/trading_ws_collect_readiness.ps1 before asking for a confirmed long WS collect."
}

if (
    (Test-Path -LiteralPath $collectApprovalContractScript) -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "trading_collect_approval_contract") -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT") -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "requires_user_approval_for_actual_collect") -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "requires_explicit_user_approval_for_actual_collect") -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "START72H") -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "replay_allowed") -and
    (Test-TextContains -Path $collectApprovalContractScript -Pattern "would_start")
) {
    Add-Check $checks "collect_approval_contract_verifier" "pass" "Collect approval contract verifier exists and cross-checks rejected replay_allowed=false state, PlanOnly preview, START72H shortcut and explicit approval before actual 72h collect."
} else {
    Add-Check $checks "collect_approval_contract_verifier" "fail" "Collect approval contract verifier is missing or incomplete." "Restore tools/trading_collect_approval_contract.ps1 before asking for START72H approval."
}

if (
    (Test-Path -LiteralPath $wsCollectApprovalPacketScript) -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "trading_ws_collect_approval_packet") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "READY_FOR_START72H_APPROVAL_PACKET") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "Get-FileFingerprint") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "sha256") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "critical_file_fingerprints") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "start_requires_exact_user_input") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "START72H") -and
    (Test-TextContains -Path $wsCollectApprovalPacketScript -Pattern "would_start")
) {
    Add-Check $checks "ws_collect_approval_packet" "pass" "WS collect approval packet script exists and records non-starting START72H evidence with SHA256 fingerprints."
} else {
    Add-Check $checks "ws_collect_approval_packet" "fail" "WS collect approval packet script is missing or incomplete." "Restore tools/trading_ws_collect_approval_packet.ps1 before asking for START72H approval."
}

if (
    (Test-Path -LiteralPath $visibleWsCollectScript) -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "readiness_guard") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "trading_ws_collect_readiness.ps1") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "Confirmed WS collect refused: readiness") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION")
) {
    Add-Check $checks "visible_ws_collect_confirmed_readiness_guard" "pass" "Confirmed WS collect wrapper runs the readiness verifier before writing the RUNNING gate or starting the child collector."
} else {
    Add-Check $checks "visible_ws_collect_confirmed_readiness_guard" "fail" "Confirmed WS collect wrapper can bypass the readiness verifier." "Run tools/trading_ws_collect_readiness.ps1 inside tools/start_ws_collect_visible.ps1 before creating active-run gate metadata."
}

if (
    (Test-Path -LiteralPath $dataSufficiencyPlannerScript) -and
    (Test-TextContains -Path $dataSufficiencyPlannerScript -Pattern "TargetSweeps") -and
    (Test-TextContains -Path $dataSufficiencyPlannerScript -Pattern "sweep_rate_per_market_hour") -and
    (Test-TextContains -Path $dataSufficiencyPlannerScript -Pattern "estimated_hours_for_target_sweeps_current_markets") -and
    (Test-TextContains -Path $dataSufficiencyPlannerScript -Pattern "next_collect_6h_is_likely_insufficient_for_event_gate") -and
    (Test-TextContains -Path $dataSufficiencyPlannerScript -Pattern "paper_forward_allowed")
) {
    Add-Check $checks "data_sufficiency_planner" "pass" "Data sufficiency planner exists and estimates sweep/trade sample size before another dense WS collect."
} else {
    Add-Check $checks "data_sufficiency_planner" "fail" "Data sufficiency planner is missing or incomplete." "Restore tools/trading_data_sufficiency_plan.ps1 before another visible WS collect decision."
}

if (
    (Test-Path -LiteralPath $denseWsCollectPlannerScript) -and
    (Test-TextContains -Path $denseWsCollectPlannerScript -Pattern "dense_ws_collect_plan") -and
    (Test-TextContains -Path $denseWsCollectPlannerScript -Pattern "dense_universe_output") -and
    (Test-TextContains -Path $denseWsCollectPlannerScript -Pattern "recommended_command_after_explicit_approval") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "dense_collect_plan") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "UniversePath") -and
    (Test-TextContains -Path $visibleWsCollectScript -Pattern "recommended_command_after_explicit_approval")
) {
    Add-Check $checks "dense_ws_collect_planner" "pass" "Visible WS PlanOnly includes a dense universe/sample-size plan before any next long collect."
} else {
    Add-Check $checks "dense_ws_collect_planner" "fail" "Dense WS collect planner is missing or not wired into visible PlanOnly." "Wire tools/trading_dense_ws_collect_plan.ps1 into tools/start_ws_collect_visible.ps1 before asking for another long collect."
}

if (
    (Test-Path -LiteralPath $wsPostprocessShortcut) -and
    (Test-Path -LiteralPath $wsPostprocessScript) -and
    (Test-TextContains -Path $wsPostprocessShortcut -Pattern "run_ws_postprocess_visible.ps1") -and
    (-not (Test-TextContains -Path $wsPostprocessShortcut -Pattern "run_mvp.ps1")) -and
    (-not (Test-TextContains -Path $wsPostprocessShortcut -Pattern "ws-postprocess")) -and
    (Test-TextContains -Path $wsPostprocessScript -Pattern "check_active_run_gate.ps1") -and
    (Test-TextContains -Path $wsPostprocessScript -Pattern "STOPPED_INCOMPLETE") -and
    (Test-TextContains -Path $wsPostprocessScript -Pattern "replay_allowed") -and
    (Test-TextContains -Path $wsPostprocessScript -Pattern "replay_grid_if_data_quality_rejected")
) {
    Add-Check $checks "visible_ws_postprocess_shortcut_alignment" "pass" "WS postprocess shortcut routes through the guarded visible wrapper; direct run_mvp.ps1/ws-postprocess bypass is absent."
} else {
    Add-Check $checks "visible_ws_postprocess_shortcut_alignment" "fail" "WS postprocess shortcut is missing, bypasses the guarded wrapper, or the wrapper lacks gate/data-quality guards." "Fix TRADING_WS_POSTPROCESS_FROM_GATE.cmd and tools/run_ws_postprocess_visible.ps1 before postprocessing a visible WS collect."
}

if (
    (Test-Path -LiteralPath $gateChecker) -and
    (Test-TextContains -Path $gateChecker -Pattern "postprocess_block") -and
    (Test-TextContains -Path $gateChecker -Pattern "raw_gate_next_step_after_ready") -and
    (Test-TextContains -Path $gateChecker -Pattern "Funding final-review guard blocked") -and
    (Test-Path -LiteralPath $nextGoalStep) -and
    (Test-TextContains -Path $nextGoalStep -Pattern "gate_postprocess_block") -and
    (Test-TextContains -Path $nextGoalStep -Pattern "gate_raw_next_step_after_ready")
) {
    Add-Check $checks "funding_postprocess_block_readback" "pass" "Active gate and next-goal step preserve guard-block evidence and override stale funding postprocess next-step."
} else {
    Add-Check $checks "funding_postprocess_block_readback" "fail" "Active gate/next-goal readback does not preserve funding postprocess block evidence." "Keep funding rank/backtest blocked until check_active_run_gate.ps1 and trading_next_goal_step.ps1 expose postprocess_block and raw next-step evidence."
}

if (Test-Path -LiteralPath $wsPostprocessScript) {
    Add-Check $checks "ws_postprocess_wrapper" "pass" "Guarded WS postprocess wrapper exists: $wsPostprocessScript."
} else {
    Add-Check $checks "ws_postprocess_wrapper" "fail" "Guarded WS postprocess wrapper is missing: $wsPostprocessScript." "Restore wrapper before postprocessing a visible WS collect."
}

if ((Test-Path -LiteralPath $wsPostprocessScript) -and (Test-TextContains -Path $wsPostprocessScript -Pattern "ws-postprocess") -and (Test-TextContains -Path $wsPostprocessScript -Pattern "replay_allowed") -and (Test-TextContains -Path $wsPostprocessScript -Pattern "replay_grid_if_data_quality_rejected")) {
    Add-Check $checks "ws_postprocess_quality_gate" "pass" "WS postprocess wrapper runs ws-postprocess and blocks replay/grid unless data-quality accepts."
} else {
    Add-Check $checks "ws_postprocess_quality_gate" "fail" "WS postprocess wrapper does not enforce replay_allowed/data-quality gating." "Wire ws-postprocess output into a hard replay/grid guard."
}

if (Test-Path -LiteralPath $wsReplayValidationScript) {
    Add-Check $checks "ws_replay_validation_wrapper" "pass" "Guarded WS replay validation wrapper exists: $wsReplayValidationScript."
} else {
    Add-Check $checks "ws_replay_validation_wrapper" "fail" "Guarded WS replay validation wrapper is missing: $wsReplayValidationScript." "Add wrapper before running ws-replay/ws-grid-search after WS postprocess."
}

if ((Test-Path -LiteralPath $wsReplayValidationScript) -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "PostprocessPath") -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "ConfirmedResearchRun") -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "replay_allowed") -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "ws-grid-search") -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "Get-FileFingerprint") -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "ExpectedManifestPath") -and (Test-TextContains -Path $wsReplayValidationScript -Pattern "expected_manifest_required_for_confirmed_research_run")) {
    Add-Check $checks "ws_replay_validation_quality_gate" "pass" "WS replay validation wrapper requires explicit postprocess artifact, replay_allowed=true, artifact fingerprints, ExpectedManifestPath and ConfirmedResearchRun for actual replay/grid."
} else {
    Add-Check $checks "ws_replay_validation_quality_gate" "fail" "WS replay validation wrapper does not enforce PostprocessPath/replay_allowed/fingerprint/ExpectedManifestPath/ConfirmedResearchRun gates." "Keep replay/grid blocked until this guard is fixed."
}

try {
    if (-not (Test-Path -LiteralPath $fundingWatchlistScript)) {
        Add-Check $checks "funding_candidate_watchlist" "fail" "Watchlist script is missing: $fundingWatchlistScript." "Restore tools/funding_candidate_watchlist.ps1."
    } elseif (-not (Test-Path -LiteralPath $fundingWatchlistJson)) {
        Add-Check $checks "funding_candidate_watchlist" "fail" "Watchlist artifact is missing: $fundingWatchlistJson." "Run tools/funding_candidate_watchlist.ps1 before interpreting a 7d collect."
    } else {
        $fundingWatchlist = Get-Content -Raw -LiteralPath $fundingWatchlistJson | ConvertFrom-Json
        $primaryWatch = [int]$fundingWatchlist.summary.primary_7d_watch
        $secondaryWatch = [int]$fundingWatchlist.summary.secondary_7d_watch
        $rankEligible = [int]$fundingWatchlist.summary.rank_eligible
        if ($fundingWatchlist.decision -eq "WATCHLIST_READY_NOT_TRADEABLE" -and ($primaryWatch + $secondaryWatch) -gt 0 -and $rankEligible -eq 0) {
            Add-Check $checks "funding_candidate_watchlist" "pass" "Watchlist ready: primary=$primaryWatch, secondary=$secondaryWatch, rank_eligible=$rankEligible; not a trade signal."
        } else {
            Add-Check $checks "funding_candidate_watchlist" "warn" "Unexpected watchlist state: decision=$($fundingWatchlist.decision), primary=$primaryWatch, secondary=$secondaryWatch, rank_eligible=$rankEligible." "Review watchlist before any 7d collect."
        }
    }
} catch {
    Add-Check $checks "funding_candidate_watchlist" "fail" "Failed to parse watchlist artifact: $($_.Exception.Message)" "Regenerate funding candidate watchlist."
}

if (Test-Path -LiteralPath $finalReviewScript) {
    Add-Check $checks "final_review_wrapper" "pass" "Guarded funding final-review wrapper exists: $finalReviewScript."
} else {
    Add-Check $checks "final_review_wrapper" "fail" "Funding final-review wrapper is missing: $finalReviewScript." "Restore wrapper before postprocess/final-review."
}

if (
    (Test-Path -LiteralPath $finalReviewScript) -and
    (Test-TextContains -Path $finalReviewScript -Pattern "AllowBlockedFundingDataset") -and
    (Test-TextContains -Path $finalReviewScript -Pattern "Funding dataset is blocked by guard review") -and
    (Test-TextContains -Path $finalReviewScript -Pattern "Refusing funding final-review/rank/backtest/paper-forward") -and
    (Test-TextContains -Path $finalReviewScript -Pattern "trading_next_goal_step.ps1")
) {
    Add-Check $checks "final_review_blocked_dataset_self_refuse" "pass" "Guarded final-review wrapper refuses already-blocked funding datasets unless explicitly overridden for guard/debug regeneration."
} else {
    Add-Check $checks "final_review_blocked_dataset_self_refuse" "fail" "Funding final-review wrapper does not self-refuse datasets already blocked by guard review." "Add a postprocess_block readback guard to tools/run_funding_final_review_visible.ps1 before invoking rank/backtest/final-review."
}

if ((Test-Path -LiteralPath $finalReviewScript) -and (Test-TextContains -Path $finalReviewScript -Pattern "funding_watchlist_review") -and (Test-TextContains -Path $finalReviewScript -Pattern "WatchlistPath")) {
    Add-Check $checks "final_review_watchlist_review" "pass" "Guarded final-review wrapper runs funding_watchlist_review after final-review artifacts are created."
} else {
    Add-Check $checks "final_review_watchlist_review" "fail" "Final-review wrapper does not run watchlist review." "Wire funding_watchlist_review.ps1 into run_funding_final_review_visible.ps1."
}

if ((Test-Path -LiteralPath $finalReviewScript) -and (Test-TextContains -Path $finalReviewScript -Pattern "blocked_by_watchlist_review") -and (Test-TextContains -Path $finalReviewScript -Pattern "funding_paper_plan_watchlist_block")) {
    Add-Check $checks "final_review_watchlist_paper_block" "pass" "Guarded final-review wrapper blocks ready paper plans when watchlist review does not support promotion."
} else {
    Add-Check $checks "final_review_watchlist_paper_block" "fail" "Final-review wrapper does not block ready paper plans after watchlist conflicts." "Add blocked_by_watchlist_review handling to run_funding_final_review_visible.ps1."
}

if (Test-Path -LiteralPath $fundingWatchlistReviewScript) {
    Add-Check $checks "funding_watchlist_review_script" "pass" "Funding watchlist review script exists: $fundingWatchlistReviewScript."
} else {
    Add-Check $checks "funding_watchlist_review_script" "fail" "Funding watchlist review script is missing: $fundingWatchlistReviewScript." "Restore anti-cherry-picking watchlist review before 7d postprocess."
}

if (Test-Path -LiteralPath $strategyAcceptanceGateScript) {
    Add-Check $checks "strategy_acceptance_gate" "pass" "Strategy acceptance gate exists: $strategyAcceptanceGateScript."
} else {
    Add-Check $checks "strategy_acceptance_gate" "fail" "Strategy acceptance gate is missing: $strategyAcceptanceGateScript." "Restore gate before accepting any strategy or paper-forward candidate."
}

if ((Test-Path -LiteralPath $strategyAcceptanceGateScript) -and (Test-TextContains -Path $strategyAcceptanceGateScript -Pattern "FundingWatchlistReviewPath") -and (Test-TextContains -Path $strategyAcceptanceGateScript -Pattern "funding_watchlist_review_not_acceptance_supporting")) {
    Add-Check $checks "strategy_acceptance_watchlist_gate" "pass" "Strategy acceptance gate requires funding watchlist review support before research promotion."
} else {
    Add-Check $checks "strategy_acceptance_watchlist_gate" "fail" "Strategy acceptance gate does not require funding watchlist review support." "Wire funding_watchlist_review into tools/trading_strategy_acceptance_gate.ps1."
}

try {
    if (-not (Test-Path -LiteralPath $fundingPostprocessPath)) {
        Add-Check $checks "funding_24h_result" "fail" "24h funding postprocess artifact is missing: $fundingPostprocessPath." "Run guarded postprocess only on final data or restore artifact."
    } else {
        $fundingPostprocess = Get-Content -Raw -LiteralPath $fundingPostprocessPath | ConvertFrom-Json
        $rankEligible = [int]$fundingPostprocess.rank_summary.rank_eligible
        $totalTrades = [int]$fundingPostprocess.backtest_metrics.total_trades
        $researchAccepted = [bool]$fundingPostprocess.research_acceptance.accepted
        if ((-not $researchAccepted) -and $rankEligible -eq 0 -and $totalTrades -eq 0) {
            Add-Check $checks "funding_24h_result" "pass" "24h funding result rejected: rank_eligible=0, total_trades=0, research_accepted=false."
        } else {
            Add-Check $checks "funding_24h_result" "warn" "24h funding result differs: rank_eligible=$rankEligible, total_trades=$totalTrades, research_accepted=$researchAccepted." "Re-read the decision report before choosing the next proof step."
        }
    }
} catch {
    Add-Check $checks "funding_24h_result" "fail" "Failed to parse 24h funding postprocess: $($_.Exception.Message)" "Fix or regenerate the postprocess artifact."
}

if ((Test-Path -LiteralPath $edgePlanPath) -and (Test-TextContains -Path $edgePlanPath -Pattern "No new YouTube/RSS/transcript") -and (Test-TextContains -Path $edgePlanPath -Pattern "High win-rate without positive expectancy")) {
    Add-Check $checks "edge_plan_document" "pass" "Edge proof plan exists and blocks channel intake plus winrate-only optimization."
} else {
    Add-Check $checks "edge_plan_document" "fail" "Edge proof plan is missing required scope/edge definitions." "Repair docs/plans/2026-06-17-trading-mvp-edge-proof-execution-plan.md."
}

if ((Test-Path -LiteralPath $masterIndexPath) -and (Test-TextContains -Path $masterIndexPath -Pattern "No new YouTube/RSS/transcript/source-packet work") -and (Test-TextContains -Path $masterIndexPath -Pattern "accepted_trading_strategies|Accepted trading strategies|no setup passes gates")) {
    Add-Check $checks "master_index_scope" "pass" "Master index documents channel freeze and no accepted high-winrate setup."
} else {
    Add-Check $checks "master_index_scope" "warn" "Master index does not clearly expose channel freeze/no-accepted-strategy state." "Update the master evidence index for operator clarity."
}

$failCount = @($checks | Where-Object { $_.status -eq "fail" }).Count
$warnCount = @($checks | Where-Object { $_.status -eq "warn" }).Count
$runningBlocked = $false
if ($gate -and [string]$gate.status -eq "RUNNING") {
    $runningBlocked = $true
}
$stoppedIncomplete = $false
if ($gate -and [string]$gate.status -eq "STOPPED_INCOMPLETE") {
    $stoppedIncomplete = $true
}

$visibleFundingCollectCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleCollectScript -Days 7 -ConfirmedLongRun"
$fundingBasisPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingBasisPlanOnlyScript -Json"
$structuralBranchPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $structuralBranchPlanOnlyScript -Json"
$crossVenueImplementationPlanOnlyCommand = "manual PlanOnly implementation: build cross-venue spot dislocation detector/backtester against existing clean data; do not start collect/grid/live/API"
$visibleWsCollectCommandResolution = Resolve-WsCollectCommands -ScriptPath $visibleWsCollectScript -PlanPreviewPath $visibleWsPlanPreviewLatest
$visibleWsCollectPreviewCommand = $visibleWsCollectCommandResolution.preview_command
$visibleWsCollectCommand = $visibleWsCollectCommandResolution.command
$wsPostprocessCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsPostprocessScript"
$wsPostprocessShortcutCommand = $wsPostprocessShortcut
$wsReplayValidationPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsReplayValidationScript -PostprocessPath <exports\trading-mvp\backtests\ws_postprocess_*.json> -ExpectedManifestPath <exports\trading-mvp\raw\ws_collect_*.json> -PlanOnly"

$nextAllowedAction = if ($runningBlocked) {
    "Only status/ETA checks. Do not run postprocess, collectors, grids, broad analysis, or code changes for the goal."
} elseif ($stoppedIncomplete) {
    "Resume the incomplete run visibly or declare the dataset incomplete before continuing."
} elseif ($failCount -gt 0) {
    "Fix failed preflight checks before continuing the edge-proof pipeline."
} elseif ($crossVenueStructuralSelectedGate) {
    "Short PlanOnly implementation work is allowed. Current proof branch is cross-venue spot dislocation/inventory-rebalance on existing clean MEXC/Gate data; no collect/grid/live/API/paper-forward."
} elseif ($fundingRejectedBaseFeesGate) {
    "Short PlanOnly branch-selection work is allowed. Current step is choosing a new non-HFT structural research branch; no collect/grid/live/API/paper-forward."
} elseif ($liquiditySweepRejectedGate) {
    "Short PlanOnly diagnostics are allowed. Current proof branch is funding/basis carry structural PlanOnly after liquidity_sweep_reversal rejection; no collect/grid/live/API/paper-forward."
} elseif ($fundingBlockedBySwarm) {
    "Short edge-proof engineering is allowed. Current proof branch is guarded visible dense WS collect planning; actual collect requires explicit user approval and -ConfirmedLongRun. Do not launch another funding collect first and do not analyze new channel content."
} else {
    "Short edge-proof engineering is allowed. A visible 7d funding/basis collect is allowed only after explicit user approval. Do not analyze new channel content."
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    ok = ($failCount -eq 0)
    status = if ($runningBlocked) { "BLOCKED_RUNNING" } elseif ($stoppedIncomplete) { "BLOCKED_STOPPED_INCOMPLETE" } elseif ($failCount -gt 0) { "FAILED_PREFLIGHT" } else { "READY_FOR_EDGE_PROOF_STEP" }
    fail_count = $failCount
    warn_count = $warnCount
    checks = @($checks)
    next_allowed_action = $nextAllowedAction
    current_scorecard = $currentScorecardPath
    funding_blocked_by_swarm = $fundingBlockedBySwarm
    liquidity_sweep_rejected_gate = $liquiditySweepRejectedGate
    funding_rejected_base_fees_gate = $fundingRejectedBaseFeesGate
    cross_venue_rejected_gate = $crossVenueRejectedGate
    listing_event_replay_rejected_gate = $listingEventReplayRejectedGate
    cross_venue_structural_selected_gate = $crossVenueStructuralSelectedGate
    swarm_status = if ($swarmStatus) { [string]$swarmStatus.status } else { "NO_SWARM_STATUS" }
    swarm_limited = [bool]($swarmStatus -and [bool]$swarmStatus.swarm_limited)
    swarm_independent_review_available = [bool]($swarmStatus -and [bool]$swarmStatus.independent_review_available)
    swarm_latest_workflow_id = if ($swarmStatus -and $swarmStatus.latest_workflow) { [string]$swarmStatus.latest_workflow.workflow_id } else { "" }
    swarm_status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json"
    trading_test_runner_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript -PlanOnly -Json"
    trading_test_full_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript"
    fee_tier_evidence_present = $feeTierEvidencePresent
    visible_ws_collect_preview_command = $visibleWsCollectPreviewCommand
    visible_ws_collect_command = $visibleWsCollectCommand
    visible_ws_collect_command_resolution = $visibleWsCollectCommandResolution
    visible_ws_collect_readiness_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectReadinessScript -Json"
    collect_approval_contract_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $collectApprovalContractScript -Json"
    ws_collect_approval_packet_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectApprovalPacketScript -Json"
    visible_ws_collect_preview_shortcut = $visibleWsPreviewShortcut
    visible_ws_collect_confirmed_shortcut = $visibleWsConfirmedShortcut
    visible_ws_collect_plan_preview_latest = $visibleWsPlanPreviewLatest
    data_sufficiency_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $dataSufficiencyPlannerScript -Json"
    dense_ws_collect_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $denseWsCollectPlannerScript -Json"
    ws_postprocess_command = $wsPostprocessCommand
    ws_postprocess_shortcut_command = $wsPostprocessShortcutCommand
    ws_replay_validation_plan_command = $wsReplayValidationPlanCommand
    funding_visible_collect_command = $visibleFundingCollectCommand
    funding_basis_planonly_command = $fundingBasisPlanOnlyCommand
    structural_branch_planonly_command = $structuralBranchPlanOnlyCommand
    visible_collect_command = if ($crossVenueStructuralSelectedGate) { $crossVenueImplementationPlanOnlyCommand } elseif ($fundingRejectedBaseFeesGate) { $structuralBranchPlanOnlyCommand } elseif ($liquiditySweepRejectedGate) { $fundingBasisPlanOnlyCommand } elseif ($fundingBlockedBySwarm) { $visibleWsCollectCommand } else { $visibleFundingCollectCommand }
    final_review_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $finalReviewScript"
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host "trading_mvp Edge Preflight" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Status: $($result.status)"
    Write-Host "Failures: $failCount; Warnings: $warnCount"
    Write-Host ""
    foreach ($check in $checks) {
        $prefix = if ($check.status -eq "pass") { "[PASS]" } elseif ($check.status -eq "warn") { "[WARN]" } else { "[FAIL]" }
        Write-Host "$prefix $($check.name): $($check.evidence)"
        if ($check.action) {
            Write-Host "       Action: $($check.action)"
        }
    }
    Write-Host ""
    Write-Host "Next allowed action:" -ForegroundColor Yellow
    Write-Host "  $nextAllowedAction"
    Write-Host ""
    Write-Host "Visible WS collect commands, only after explicit approval for actual run:"
    Write-Host "  swarm status: $($result.swarm_status_command)"
    Write-Host "  test runner plan: $($result.trading_test_runner_command)"
    Write-Host "  full tests: $($result.trading_test_full_command)"
    Write-Host "  preview: $($result.visible_ws_collect_preview_command)"
    Write-Host "  readiness: $($result.visible_ws_collect_readiness_command)"
    Write-Host "  approval packet: $($result.ws_collect_approval_packet_command)"
    Write-Host "  actual:  $($result.visible_ws_collect_command)"
    Write-Host "  postprocess after ready: $($result.ws_postprocess_command)"
    Write-Host "  replay validation plan: $($result.ws_replay_validation_plan_command)"
    Write-Host "  structural branch plan: $($result.structural_branch_planonly_command)"
    Write-Host ""
    Write-Host "Current visible collect command, only after explicit approval:"
    Write-Host "  $($result.visible_collect_command)"
    Write-Host "Final review command, only after final manifest:"
    Write-Host "  $($result.final_review_command)"
}

if ($failCount -gt 0) {
    exit 2
}
exit 0
