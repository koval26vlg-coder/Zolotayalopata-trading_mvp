param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$scorecardPath = Join-Path $repoRoot "exports\trading-mvp\analysis\anufriev_strategy_scorecard_current_20260628.csv"
$thresholdPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_economic_thresholds_20260617.csv"
$masterIndexPath = Join-Path $repoRoot "docs\analysis\2026-06-17-anufriev-master-evidence-index.md"
$edgePlanPath = Join-Path $repoRoot "docs\plans\2026-06-17-trading-mvp-edge-proof-execution-plan.md"
$edgePlanCsvPath = Join-Path $repoRoot "exports\trading-mvp\analysis\trading_mvp_edge_proof_execution_plan_20260617.csv"
$backlogPath = Join-Path $repoRoot "exports\trading-mvp\analysis\trading_mvp_evidence_to_engineering_backlog_20260617.csv"
$visibleCollectScript = Join-Path $repoRoot "tools\start_funding_collect_visible.ps1"
$finalReviewScript = Join-Path $repoRoot "tools\run_funding_final_review_visible.ps1"
$edgePreflightScript = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$swarmStatusScript = Join-Path $repoRoot "tools\trading_swarm_status.ps1"
$tradingTestRunnerScript = Join-Path $repoRoot "tools\run_trading_tests.ps1"
$strategyAcceptanceGateScript = Join-Path $repoRoot "tools\trading_strategy_acceptance_gate.ps1"
$nextGoalStepScript = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$fundingViabilityGapScript = Join-Path $repoRoot "tools\funding_viability_gap.ps1"
$fundingCostAssumptionGateScript = Join-Path $repoRoot "tools\funding_cost_assumption_gate.ps1"
$fundingCandidateWatchlistScript = Join-Path $repoRoot "tools\funding_candidate_watchlist.ps1"
$fundingWatchlistReviewScript = Join-Path $repoRoot "tools\funding_watchlist_review.ps1"
$fundingBasisPlanOnlyScript = Join-Path $repoRoot "tools\trading_funding_basis_planonly.ps1"
$structuralBranchPlanOnlyScript = Join-Path $repoRoot "tools\trading_structural_branch_planonly.ps1"
$slowLiquidityPlanOnlyScript = Join-Path $repoRoot "tools\trading_slow_liquidity_regime_breakout_retest_planonly.ps1"
$slowLiquidityDataAvailabilityPreflightScript = Join-Path $repoRoot "tools\trading_slow_liquidity_data_availability_preflight.ps1"
$slowLiquidityHistoryDataPlanScript = Join-Path $repoRoot "tools\trading_slow_liquidity_history_data_plan.ps1"
$slowLiquidityFixedSignalPlanScript = Join-Path $repoRoot "tools\trading_slow_liquidity_fixed_signal_planonly.ps1"
$slowLiquidityFeatureNormalizerScript = Join-Path $repoRoot "tools\trading_slow_liquidity_feature_normalizer_planonly.ps1"
$spotPerpBasisPlanOnlyScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_mean_reversion_planonly.ps1"
$spotPerpBasisAvailabilityPreflightScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_availability_preflight.ps1"
$spotPerpBasisPublicProbeScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_public_probe.ps1"
$listingEventPlanOnlyScript = Join-Path $repoRoot "tools\trading_listing_event_planonly.ps1"
$listingEventNormalizerPlanOnlyScript = Join-Path $repoRoot "tools\trading_listing_event_normalizer_planonly.ps1"
$listingEventHistoryPlanOnlyScript = Join-Path $repoRoot "tools\trading_listing_event_history_planonly.ps1"
$listingEventHistoryCollectPreviewScript = Join-Path $repoRoot "tools\trading_listing_event_history_collect_preview.ps1"
$listingEventHistoryCollectApprovalPacketScript = Join-Path $repoRoot "tools\trading_listing_event_history_collect_approval_packet.ps1"
$listingEventHistoryCollectVisibleScript = Join-Path $repoRoot "tools\start_listing_event_history_collect_visible.ps1"
$listingEventHistoryDataQualityScript = Join-Path $repoRoot "tools\trading_listing_event_history_data_quality.ps1"
$listingEventHistoryAvailabilityPreflightScript = Join-Path $repoRoot "tools\trading_listing_event_history_availability_preflight.ps1"
$listingEventReplayPlanOnlyScript = Join-Path $repoRoot "tools\trading_listing_event_replay_planonly.ps1"
$branchSelectorScript = Join-Path $repoRoot "tools\trading_branch_selector.ps1"
$pitCrossVenueForwardOosVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_forward_oos_visible.ps1"
$spotPitEventForwardVisibleScript = Join-Path $repoRoot "tools\start_spot_pit_event_forward_visible.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$crossVenueFullOutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"
$visibleWsCollectScript = Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"
$wsCollectReadinessScript = Join-Path $repoRoot "tools\trading_ws_collect_readiness.ps1"
$collectApprovalContractScript = Join-Path $repoRoot "tools\trading_collect_approval_contract.ps1"
$wsCollectApprovalPacketScript = Join-Path $repoRoot "tools\trading_ws_collect_approval_packet.ps1"
$sweepReversalGateScript = Join-Path $repoRoot "tools\sweep_reversal_acceptance_gate.ps1"
$researchGoalPlanPath = Join-Path $repoRoot "docs\plans\2026-06-15-trading-mvp-research-goal.md"
$feeTierEvidencePath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_account_fee_tiers_current.json"
$publicFeeObservationsPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_public_fee_observations_20260627.json"
$preview7dFundingShortcut = Join-Path $repoRoot "TRADING_PREVIEW_7D_FUNDING.cmd"
$start7dFundingShortcut = Join-Path $repoRoot "TRADING_START_7D_FUNDING_CONFIRMED.cmd"
$previewDenseWsShortcut = Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"
$startDenseWsShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"
$visibleWsPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"
$visibleWsLegacyPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_6h_plan_preview_latest.json"
if ((-not (Test-Path -LiteralPath $visibleWsPlanPreviewLatest)) -and (Test-Path -LiteralPath $visibleWsLegacyPlanPreviewLatest)) {
    $visibleWsPlanPreviewLatest = $visibleWsLegacyPlanPreviewLatest
}

function Read-CsvIfExists {
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

function Test-FileContains {
    param(
        [string]$Path,
        [string]$Needle
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    return [bool](Select-String -LiteralPath $Path -SimpleMatch -Pattern $Needle -Quiet)
}

function Get-SummaryMetric {
    param(
        [string]$Summary,
        [string]$Name
    )
    if ([string]::IsNullOrWhiteSpace($Summary)) {
        return $null
    }
    $escaped = [regex]::Escape($Name)
    $match = [regex]::Match($Summary, "(^|;\s*)$escaped=([^;]+)")
    if (-not $match.Success) {
        return $null
    }
    return $match.Groups[2].Value.Trim()
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

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
$rawGate = Read-JsonFileOrNull -Path $gatePath
$gateHistory = if ($rawGate) { $rawGate } else { $gate }
$crossVenueFullResult = Read-JsonFileOrNull -Path $crossVenueFullOutputPath
if (-not $crossVenueFullResult -and $gateHistory.PSObject.Properties.Name -contains "last_cross_venue_dislocation_full_output_path") {
    $crossVenueFullResult = Read-JsonFileOrNull -Path ([string]$gateHistory.last_cross_venue_dislocation_full_output_path)
}
$listingEventReplayResult = $null
if ($gateHistory.PSObject.Properties.Name -contains "last_listing_event_replay_output_path") {
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
$scorecard = Read-CsvIfExists -Path $scorecardPath
$thresholds = Read-CsvIfExists -Path $thresholdPath
$edgePlan = Read-CsvIfExists -Path $edgePlanCsvPath
$backlog = Read-CsvIfExists -Path $backlogPath
$currentFundingThresholds = @($thresholds | Where-Object { $_.scenario -eq "current_taker_like" })

$acceptedTradingRows = @(
    $scorecard | Where-Object {
        $_.verdict -notin @(
            "rejected",
            "failed",
            "inconclusive",
            "untested",
            "excluded_from_trading_bot",
            "tooling_only",
            "mandatory_gate",
            "blocked_swarm",
            "blocked"
        )
    }
)

$fundingRow = $scorecard | Where-Object { $_.strategy_family -eq "Funding/basis carry current cost model" } | Select-Object -First 1
$blockedRows = @($scorecard | Where-Object { $_.verdict -in @("rejected", "failed") })
$inconclusiveRows = @($scorecard | Where-Object { $_.verdict -eq "inconclusive" })
$scopeFreezeRow = $backlog | Where-Object { $_.backlog_id -eq "P0-003" } | Select-Object -First 1
$primaryEdgeStep = $edgePlan | Where-Object { $_.step_id -eq "E3" } | Select-Object -First 1
$fundingBlockedBySwarm = (
    (Test-FileContains -Path $researchGoalPlanPath -Needle "Swarm L1 review 2026-06-27") -and
    (Test-FileContains -Path $researchGoalPlanPath -Needle "Swarm L2 review 2026-06-27") -and
    (Test-FileContains -Path $researchGoalPlanPath -Needle "Funding carry remains blocked for paper-forward")
)
$swarmStatus = $null
try {
    if (Test-Path -LiteralPath $swarmStatusScript) {
        $swarmStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json | ConvertFrom-Json
    }
} catch {
    $swarmStatus = [pscustomobject]@{
        status = "SWARM_STATUS_ERROR"
        read_error = $_.Exception.Message
        swarm_limited = $true
        independent_review_available = $false
        recommended_action = "continue_manual_codex_until_swarm_status_is_fixed"
    }
}
$swarmLimited = [bool]($swarmStatus -and [bool]$swarmStatus.swarm_limited)
$swarmLatestWorkflowId = if ($swarmStatus -and $swarmStatus.latest_workflow) { [string]$swarmStatus.latest_workflow.workflow_id } else { "" }
$swarmRecommendedAction = if ($swarmStatus) { [string]$swarmStatus.recommended_action } else { "no_swarm_status_available" }
$feeTierEvidencePresent = Test-Path -LiteralPath $feeTierEvidencePath
$liquiditySweepRejectedGate = (
    ([string]$gate.next_goal_decision -eq "LIQUIDITY_SWEEP_REVERSAL_REJECTED_SELECT_NEXT_BRANCH") -or
    ([string]$gate.next_goal_decision -eq "FUNDING_BASIS_CARRY_PLANONLY_CURRENT_COST_NOT_ACCEPTED") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "liquidity_sweep_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "rejected"
    )
)
$fundingRejectedBaseFeesGate = (
    ([string]$gate.next_goal_decision -eq "SELECT_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "funding_basis_carry_structural_planonly" -and
        [string]$gate.strategy_branch_status.verdict -eq "rejected_base_fees"
    )
)
$crossVenueRejectedGate = (
    (-not ([string]$gate.next_goal_decision -eq "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL")) -and
    (
        $crossVenueFullRejectedByArtifact -or
        ([string]$gate.next_goal_decision -eq "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "cross_venue_spot_dislocation_inventory_rebalance" -and
            [string]$gate.strategy_branch_status.verdict -in @("rejected_base_fees", "rejected_full_scan_base_fees", "rejected_no_net_edge_after_base_fees", "verified_rejected_no_net_edge_after_base_costs")
        )
    )
)
$currentCrossVenueSpotClosureGate = [bool](
    [string]$gate.next_goal_decision -eq "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH" -and
    $gateHistory.PSObject.Properties.Name -contains "last_cross_venue_spot_full_scan_audit_decision" -and
    [string]$gateHistory.last_cross_venue_spot_full_scan_audit_decision -eq "CROSS_VENUE_SPOT_FULL_SCAN_VERIFIED_REJECTED_NO_NET_EDGE_AFTER_BASE_COSTS"
)
$currentLeadLagClosureGate = [bool](
    [string]$gate.next_goal_decision -eq "CROSS_VENUE_SPOT_LEAD_LAG_VERIFIED_REJECTED_SELECT_NEW_STRUCTURAL_HYPOTHESIS_PLANONLY" -and
    $gateHistory.PSObject.Properties.Name -contains "last_cross_venue_lead_lag_audit_decision" -and
    [string]$gateHistory.last_cross_venue_lead_lag_audit_decision -eq "CROSS_VENUE_SPOT_LEAD_LAG_VERIFIED_REJECTED_NO_FIXED_SIGNALS"
)
$listingEventSelectedGate = (
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY*") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_CALENDAR*") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_NORMALIZER*") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_HISTORY*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -in @("planonly_selected_not_tested", "planonly_needs_event_calendar", "planonly_ready_for_event_normalizer", "calendar_partial_needs_delisted_or_nontradable_coverage", "calendar_bias_control_pass_ready_for_normalizer", "normalizer_ready_for_event_replay_planonly", "normalizer_insufficient_overlap_needs_event_ohlcv_history", "normalizer_blocked", "history_planonly_ready_for_visible_collect_preview", "history_quality_accepted_ready_for_normalizer", "history_quality_rejected", "history_availability_preflight_planonly_ready", "history_availability_preflight_accepted", "history_availability_preflight_rejected")
    )
)
$slowLiquiditySelectedGate = (
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_HISTORY_DATA_PLAN*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_FIXED_SIGNAL*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_FEATURE_NORMALIZER*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest"
    )
)
$slowLiquidityDataAvailabilityReadyGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "planonly_ready_for_data_availability_preflight"
    )
)
$slowLiquidityDataAvailabilityAcceptedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "data_availability_preflight_accepted_ready_for_fixed_signal_planonly"
    )
)
$slowLiquidityDataAvailabilityRejectedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_HISTORY_PLAN") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "data_availability_preflight_rejected_needs_history_plan"
    )
)
$slowLiquidityHistoryDataPlanReadyGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_data_plan_ready_awaiting_explicit_approval"
    )
)
$slowLiquidityHistoryQualityAcceptedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_quality_accepted_ready_for_fixed_signal_planonly"
    )
)
$slowLiquidityFixedSignalReadyGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "fixed_signal_planonly_ready_for_feature_normalizer"
    )
)
$slowLiquidityFeatureNormalizerReadyGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_READY_FOR_FIXED_REPLAY_VALIDATION") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "feature_normalizer_ready_for_fixed_replay_validation"
    )
)
$slowLiquidityFeatureNormalizerRejectedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "feature_normalizer_rejected_insufficient_events"
    )
)
$spotPerpBasisRejectedVerdicts = @(
    "availability_preflight_rejected",
    "public_probe_rejected",
    "public_probe_rejected_rescope",
    "rejected_rescope"
)
$spotPerpBasisRejectedGate = (
    (-not $slowLiquiditySelectedGate) -and
    (
        ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") -or
        ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED*") -or
        ([string]$gateHistory.last_spot_perp_basis_public_probe_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
            [string]$gate.strategy_branch_status.verdict -in $spotPerpBasisRejectedVerdicts
        )
    )
)
$spotPerpBasisSelectedGate = (
    (-not $spotPerpBasisRejectedGate) -and
    (
        ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY*") -or
        ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT*") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding"
        )
    )
)
$spotPerpBasisAvailabilityPreflightReadyGate = (
    ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
        [string]$gate.strategy_branch_status.verdict -eq "planonly_scaffold_ready_for_availability_preflight"
    )
)
$spotPerpBasisAvailabilityAwaitingProbeGate = (
    ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
        [string]$gate.strategy_branch_status.verdict -eq "availability_preflight_ready_for_public_probe"
    )
)
$spotPerpBasisAvailabilityRejectedGate = (
    $spotPerpBasisRejectedGate -or
    ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
        [string]$gate.strategy_branch_status.verdict -in $spotPerpBasisRejectedVerdicts
    )
)
$listingEventReplayRejectedGate = (
    (-not ([string]$gate.next_goal_decision -eq "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL")) -and
    (-not $slowLiquiditySelectedGate) -and
    (-not $spotPerpBasisSelectedGate) -and
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
$listingEventReplayCandidateGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_REPLAY_PLANONLY_CANDIDATE_REQUIRES_INDEPENDENT_VALIDATION") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "replay_planonly_candidate_requires_validation"
    )
)
$listingEventNormalizerReadyGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_CALENDAR_BIAS_CONTROL_PASS_READY_FOR_NORMALIZER") -or
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_NORMALIZER") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -in @("calendar_bias_control_pass_ready_for_normalizer", "history_quality_accepted_ready_for_normalizer")
    )
)
$listingEventHistoryDataQualityPendingGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_collect_completed_ready_for_data_quality"
    )
)
$listingEventHistoryDataQualityRejectedGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_quality_rejected"
    )
)
$listingEventHistoryAvailabilityReadyGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_availability_preflight_planonly_ready"
    )
)
$listingEventHistoryAvailabilityAcceptedGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_availability_preflight_accepted"
    )
)
$listingEventHistoryAvailabilityRejectedGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_RESAMPLE_OR_GATE_FIX") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_availability_preflight_rejected"
    )
)
$listingEventHistoryPlanReadyGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_NORMALIZER_PLANONLY_INSUFFICIENT_OVERLAP_NEEDS_EVENT_OHLCV_HISTORY") -or
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_PLANONLY_READY_FOR_VISIBLE_HISTORY_COLLECT_APPROVAL") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_HISTORY_COLLECT_PREVIEW*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -in @("normalizer_insufficient_overlap_needs_event_ohlcv_history", "history_planonly_ready_for_visible_collect_preview", "history_collect_preview_ready_awaiting_explicit_approval", "history_collect_preview_blocked")
    )
)
$listingEventHistoryCollectPreviewAwaitingApprovalGate = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "history_collect_preview_ready_awaiting_explicit_approval"
    )
)
$crossVenueStructuralSelectedGate = (
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
$spotPitEventForwardApprovalReadyGate = (
    ([string]$gate.next_goal_decision -eq "SPOT_PIT_EVENT_FORWARD_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "spot_pit_idiosyncratic_crash_reclaim_1m" -and
        [string]$gate.strategy_branch_status.verdict -eq "approval_packet_ready_awaiting_explicit_visible_confirmation"
    )
)
$forwardOosApprovalReadyGate = (
    ([string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "pit_linear_perp_cross_venue_forward_oos" -and
        [string]$gate.strategy_branch_status.verdict -eq "approval_packet_ready_awaiting_explicit_visible_collect_confirmation"
    )
)
$fundingSummaryFromScorecard = if ($fundingRow) { $fundingRow.key_metric_summary } else { "not-specified" }
$fundingRowsFromScorecard = if ($fundingRow) { Get-SummaryMetric -Summary $fundingRow.key_metric_summary -Name "rows" } else { $null }
$fundingErrorsFromScorecard = if ($fundingRow) { Get-SummaryMetric -Summary $fundingRow.key_metric_summary -Name "errors" } else { $null }

$nextAllowedAction = if ($gate.status -eq "RUNNING") {
    "Only status/ETA checks. Do not run postprocess, collectors, grids, broad analysis, or code changes for the goal."
} elseif ($gate.status -eq "STOPPED_INCOMPLETE") {
    "Resume the incomplete run visibly or declare the dataset incomplete before continuing."
} elseif ($spotPitEventForwardApprovalReadyGate) {
    "Spot PIT event forward approval packet is sealed. Await explicit confirmation for the visible research collect; 2h data-quality and 48h futility gates will stop weak/broken evidence early. No replay/grid/live/API/paper-forward."
} elseif ($currentCrossVenueSpotClosureGate) {
    "The MEXC/Gate spot cross-venue branch is verified rejected after the clean-slice full scan. Select a new structural hypothesis PlanOnly using existing data; do not rerun/grid-tune/OOS this branch or start collect/live/API/paper-forward."
} elseif ($forwardOosApprovalReadyGate) {
    "Forward-OOS linear-perp approval packet is sealed. Await explicit confirmation for the visible 72-96h collect; no replay/grid/live/API/paper-forward."
} elseif ($slowLiquiditySelectedGate) {
    if ($slowLiquidityFeatureNormalizerReadyGate) {
        "slow_liquidity_regime_breakout_retest feature normalizer is ready. Next step is fixed replay-validation PlanOnly; no grid/live/API/paper-forward, parameters frozen."
    } elseif ($slowLiquidityFeatureNormalizerRejectedGate) {
        "slow_liquidity_regime_breakout_retest feature normalizer rejected the fixed v0 event set as insufficient. Do not replay/grid; rescope/reject branch or plan larger independent history."
    } elseif ($slowLiquidityFixedSignalReadyGate) {
        "slow_liquidity_regime_breakout_retest fixed v0 signal PlanOnly is ready. Next step is feature normalizer PlanOnly on clean 1h/4h two-venue slice; no grid/live/API/paper-forward, and replay only after normalizer artifact exists."
    } elseif ($slowLiquidityHistoryQualityAcceptedGate) {
        "slow_liquidity history data-quality accepted. Next step is fixed v0 signal PlanOnly; no replay/grid/live/API/paper-forward."
    } elseif ($slowLiquidityHistoryDataPlanReadyGate) {
        "Slow-liquidity history data plan is ready. Await explicit approval before implementing/running visible public OHLCV history collect; no replay/grid/live/API/paper-forward."
    } elseif ($slowLiquidityDataAvailabilityRejectedGate) {
        "slow_liquidity_regime_breakout_retest data availability preflight rejected current local data. Next step is history data plan/approval packet PlanOnly; no collect/grid/replay/live/API/paper-forward."
    } elseif ($slowLiquidityDataAvailabilityAcceptedGate) {
        "slow_liquidity_regime_breakout_retest data availability preflight accepted coverage. Next step is fixed v0 signal PlanOnly; no grid/replay/live/API/paper-forward."
    } else {
        "slow_liquidity_regime_breakout_retest PlanOnly is selected. Next step is read-only data availability preflight; no collect/grid/replay/live/API/paper-forward."
    }
} elseif ($spotPerpBasisAvailabilityAwaitingProbeGate) {
    "Await explicit confirmation for a short visible public REST spot/perp availability probe. Do not start actual collect/grid/replay/live/API/paper-forward."
} elseif ($spotPerpBasisAvailabilityRejectedGate) {
    "spot_perp_basis_mean_reversion_no_funding availability/public probe is rejected. Rescope/select another branch; no collect/grid/replay/live/API/paper-forward."
} elseif ($spotPerpBasisAvailabilityPreflightReadyGate) {
    "Run spot/perp basis availability preflight PlanOnly. No collect/grid/replay/live/API/paper-forward."
} elseif ($spotPerpBasisSelectedGate) {
    "spot_perp_basis_mean_reversion_no_funding is selected. Next step is PlanOnly scaffold / paired spot-perp availability preflight; no collect/grid/replay/live/API/paper-forward."
} elseif ($listingEventReplayRejectedGate) {
    "Listing-event drift/reversal fixed replay PlanOnly is rejected on current evidence. Next step is selecting a new non-HFT structural branch PlanOnly or designing a larger independent listing-event sample; no collect/grid/replay/live/API/paper-forward."
} elseif ($listingEventReplayCandidateGate) {
    "Listing-event drift/reversal is only a candidate. Build an independent validation packet before any paper-forward; no grid/live/API/paper-forward."
} elseif ($listingEventHistoryAvailabilityReadyGate) {
    "Await explicit confirmation to run a short visible public REST availability probe. Do not start actual collect/grid/replay/live/API/paper-forward."
} elseif ($listingEventHistoryAvailabilityAcceptedGate) {
    "Build revised visible OHLCV history collect approval packet. Actual collect still requires explicit confirmation; no replay/grid/live/API/paper-forward."
} elseif ($listingEventHistoryAvailabilityRejectedGate) {
    "Listing-event history availability probe rejected current coverage. Resample/fix Gate history mapping before any actual collect/grid/replay/live/API/paper-forward."
} elseif ($listingEventNormalizerReadyGate) {
    "Listing calendar passed bias controls. Next step is read-only listing-event normalizer PlanOnly against the current clean WS slice; no collect/grid/live/API/paper-forward."
} elseif ($listingEventHistoryDataQualityRejectedGate) {
    "Listing-event history data-quality rejected the collected dataset. Do not replay/grid; run two-venue availability preflight before any repeated collect."
} elseif ($listingEventHistoryDataQualityPendingGate) {
    "Listing-event OHLCV history collect completed. Next step is guarded data-quality; no replay/grid/live/API/paper-forward."
} elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) {
    "Listing-event OHLCV history collect preview is ready. Await explicit user approval before implementing/running visible public-history collect; no replay/grid/live/API/paper-forward."
} elseif ($listingEventHistoryPlanReadyGate) {
    "Listing-event normalizer found insufficient current-slice overlap. Next step is event OHLCV history collect preview PlanOnly; no actual collect/grid/replay/live/API/paper-forward without approval."
} elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) {
    "cross_venue_spot_dislocation_inventory_rebalance is rejected by full scan under base fees/buffers. Next step is listing_event_drift_reversal PlanOnly research scaffold; no collect/grid/live/API/paper-forward."
} elseif ($crossVenueStructuralSelectedGate) {
    "cross_venue_spot_dislocation_inventory_rebalance is selected. Next step is a read-only PlanOnly detector/backtester on existing clean MEXC/Gate data; no collect/grid/live/API/paper-forward."
} elseif ($fundingRejectedBaseFeesGate) {
    "Funding/basis is rejected under base/VIP0/no-volume fees. Next step is a new non-HFT structural branch PlanOnly; no collect/grid/live/API/paper-forward."
} elseif ($liquiditySweepRejectedGate) {
    "liquidity_sweep_reversal is rejected by active validation gate. Next step is funding/basis carry PlanOnly diagnostics; no collect/grid/live/API/paper-forward."
} elseif ($fundingBlockedBySwarm -and $feeTierEvidencePresent) {
    "Funding carry is blocked by 7d evidence and `Рой` L1/L2 review, but fee-tier evidence exists. Validate the fee evidence through the cost gate before choosing a new branch."
} elseif ($fundingBlockedBySwarm) {
    $manualFallback = if ($swarmLimited) { " Latest swarm checkpoint is swarm_limited, so Codex manual fallback is active until swarm runtime recovers." } else { "" }
    "Funding carry is blocked by 7d evidence and `Рой` L1/L2 review. No fee-tier evidence is present, so the next branch is spot maker liquidity sweep/reversal event-quality proof tooling. No long collect without explicit approval.$manualFallback"
} else {
    "Edge-first only. If explicitly approved: run visible 7d funding/basis collect. Otherwise continue only short trading_mvp edge-proof engineering/gate work. Do not analyze new channel content."
}

$visibleWsCollectCommandResolution = Resolve-WsCollectCommands -ScriptPath $visibleWsCollectScript -PlanPreviewPath $visibleWsPlanPreviewLatest
$visibleWsCollectPreviewCommand = $visibleWsCollectCommandResolution.preview_command
$visibleWsCollectCommand = $visibleWsCollectCommandResolution.command
$visibleFundingCollectPreviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleCollectScript -Days 7 -PlanOnly"
$visibleFundingCollectCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleCollectScript -Days 7 -ConfirmedLongRun"
$forwardOosPlanPath = if ($gateHistory.PSObject.Properties.Name -contains "forward_oos_plan_path") { [string]$gateHistory.forward_oos_plan_path } else { [string]$gate.readiness_output_path }
$forwardOosPreviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueForwardOosVisibleScript`" -PlanPath `"$forwardOosPlanPath`" -PlanOnly -Json"
$forwardOosCollectCommand = if ($forwardOosApprovalReadyGate -and $gate.command_after_explicit_approval) { [string]$gate.command_after_explicit_approval } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueForwardOosVisibleScript`" -PlanPath `"$forwardOosPlanPath`" -ConfirmedForwardOosCollect" }
$spotPitEventApprovalPacketPath = if ($gateHistory.PSObject.Properties.Name -contains "spot_pit_event_forward_approval_packet_path") { [string]$gateHistory.spot_pit_event_forward_approval_packet_path } else { [string]$gate.readiness_output_path }
$spotPitEventPreviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$spotPitEventForwardVisibleScript`" -ApprovalPacketPath `"$spotPitEventApprovalPacketPath`" -PlanOnly -Json"
$spotPitEventCollectCommand = if ($gate.command_after_explicit_approval) { [string]$gate.command_after_explicit_approval } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$spotPitEventForwardVisibleScript`" -ApprovalPacketPath `"$spotPitEventApprovalPacketPath`" -ConfirmedSpotPitEventForwardCollect" }
$fundingBasisPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingBasisPlanOnlyScript -Json"
$structuralBranchPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $structuralBranchPlanOnlyScript -Json"
$structuralBranchPlanOnlyUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $structuralBranchPlanOnlyScript -UpdateGate -Json"
$slowLiquidityPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityPlanOnlyScript -Json"
$slowLiquidityPlanOnlyUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityPlanOnlyScript -UpdateGate -Json"
$slowLiquidityDataAvailabilityPreflightCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityDataAvailabilityPreflightScript -Json"
$slowLiquidityDataAvailabilityPreflightUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityDataAvailabilityPreflightScript -UpdateGate -Json"
$spotPerpBasisPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPlanOnlyScript -Json"
$spotPerpBasisAvailabilityPreflightCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisAvailabilityPreflightScript -Json"
$spotPerpBasisAvailabilityPreflightUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisAvailabilityPreflightScript -UpdateGate -Json"
$spotPerpBasisPublicProbePlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -UpdateGate -Json"
$spotPerpBasisPublicProbeConfirmedCommand = if ($spotPerpBasisAvailabilityAwaitingProbeGate -and $gate.command_after_explicit_approval) { [string]$gate.command_after_explicit_approval } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json" }
$spotPerpBasisActivePlanOnlyCommand = if ($spotPerpBasisAvailabilityPreflightReadyGate) { $spotPerpBasisAvailabilityPreflightUpdateGateCommand } elseif ($spotPerpBasisAvailabilityAwaitingProbeGate) { $spotPerpBasisPublicProbePlanCommand } elseif ($spotPerpBasisAvailabilityRejectedGate) { $structuralBranchPlanOnlyCommand } else { $spotPerpBasisPlanOnlyCommand }
$crossVenueImplementationPlanOnlyCommand = "manual PlanOnly implementation: build cross-venue spot dislocation detector/backtester against existing clean data; do not start collect/grid/live/API"
$listingEventPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventPlanOnlyScript -Json"
$listingEventNormalizerPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventNormalizerPlanOnlyScript -Json"
$listingEventHistoryPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -Json"
$listingEventHistoryCollectPreviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectPreviewScript -Json"
$listingEventHistoryCollectApprovalPacketCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectApprovalPacketScript -Json"
$listingEventHistoryCollectVisiblePlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectVisibleScript -PlanOnly"
$listingEventHistoryCollectVisibleCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectVisibleScript -ConfirmedListingHistoryCollect"
$listingEventHistoryDataQualityCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryDataQualityScript -Json"
$listingEventHistoryDataQualityUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryDataQualityScript -UpdateGate -Json"
$listingEventHistoryRecollectPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -Json"
$listingEventHistoryAvailabilityPreflightCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryAvailabilityPreflightScript -Json"
$listingEventHistoryAvailabilityPreflightUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryAvailabilityPreflightScript -UpdateGate -Json"
$listingEventHistoryAvailabilityPublicProbeCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryAvailabilityPreflightScript -ConfirmedPublicProbe -UpdateGate -Json"
$listingEventReplayPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventReplayPlanOnlyScript -Json"
$listingEventReplayValidationPacketCommand = "manual PlanOnly implementation: build independent listing-event validation packet; no grid/live/API/paper-forward"
$listingEventActivePlanOnlyCommand = if ($listingEventReplayRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($listingEventReplayCandidateGate) { $listingEventReplayValidationPacketCommand } elseif ($listingEventHistoryAvailabilityReadyGate) { $listingEventHistoryAvailabilityPublicProbeCommand } elseif ($listingEventHistoryAvailabilityAcceptedGate) { $listingEventHistoryCollectApprovalPacketCommand } elseif ($listingEventHistoryAvailabilityRejectedGate) { $listingEventHistoryCollectPreviewCommand } elseif ($listingEventNormalizerReadyGate) { $listingEventNormalizerPlanOnlyCommand } elseif ($listingEventHistoryDataQualityPendingGate) { $listingEventHistoryDataQualityCommand } elseif ($listingEventHistoryDataQualityRejectedGate) { $listingEventHistoryAvailabilityPreflightUpdateGateCommand } elseif ($listingEventHistoryPlanReadyGate) { $listingEventHistoryCollectPreviewCommand } else { $listingEventPlanOnlyCommand }
$listingEventActiveAfterApprovalCommand = if ($listingEventHistoryCollectPreviewAwaitingApprovalGate) { $listingEventHistoryCollectVisibleCommand } else { $listingEventActivePlanOnlyCommand }
$slowLiquidityHistoryPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityHistoryDataPlanScript -Json"
$slowLiquidityHistoryPlanUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityHistoryDataPlanScript -UpdateGate -Json"
$slowLiquidityHistoryAwaitApprovalCommand = "await explicit user approval: подтверждаю visible slow-liquidity OHLCV history collect"
$slowLiquidityFixedSignalPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedSignalPlanScript -Json"
$slowLiquidityFixedSignalPlanUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedSignalPlanScript -UpdateGate -Json"
$slowLiquidityFeatureNormalizerCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFeatureNormalizerScript -Json"
$slowLiquidityFeatureNormalizerUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFeatureNormalizerScript -UpdateGate -Json"
$slowLiquidityFixedReplayValidationCommand = "manual PlanOnly implementation: run fixed slow-liquidity replay-validation from feature normalizer artifact; no grid/live/API/paper-forward"
$slowLiquidityRejectedRescopeCommand = "manual PlanOnly decision: reject/rescope slow-liquidity fixed v0 or build larger-history approval packet; no replay/grid/live/API/paper-forward"
$slowLiquidityActivePlanOnlyCommand = if ($slowLiquidityFeatureNormalizerReadyGate) { $slowLiquidityFixedReplayValidationCommand } elseif ($slowLiquidityFeatureNormalizerRejectedGate) { $slowLiquidityRejectedRescopeCommand } elseif ($slowLiquidityFixedSignalReadyGate) { $slowLiquidityFeatureNormalizerUpdateGateCommand } elseif ($slowLiquidityHistoryQualityAcceptedGate) { $slowLiquidityFixedSignalPlanUpdateGateCommand } elseif ($slowLiquidityHistoryDataPlanReadyGate) { $slowLiquidityHistoryAwaitApprovalCommand } elseif ($slowLiquidityDataAvailabilityReadyGate) { $slowLiquidityDataAvailabilityPreflightUpdateGateCommand } elseif ($slowLiquidityDataAvailabilityRejectedGate) { $slowLiquidityHistoryPlanUpdateGateCommand } elseif ($slowLiquidityDataAvailabilityAcceptedGate) { $slowLiquidityFixedSignalPlanUpdateGateCommand } else { $slowLiquidityPlanOnlyCommand }
$legacyVisibleCollectPreviewCommand = if ($spotPitEventForwardApprovalReadyGate) { $spotPitEventPreviewCommand } elseif ($currentCrossVenueSpotClosureGate) { $structuralBranchPlanOnlyCommand } elseif ($forwardOosApprovalReadyGate) { $forwardOosPreviewCommand } elseif ($slowLiquiditySelectedGate) { $slowLiquidityActivePlanOnlyCommand } elseif ($spotPerpBasisAvailabilityRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($spotPerpBasisSelectedGate) { $spotPerpBasisActivePlanOnlyCommand } elseif ($listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate) { $listingEventActivePlanOnlyCommand } elseif ($crossVenueStructuralSelectedGate) { $crossVenueImplementationPlanOnlyCommand } elseif ($fundingRejectedBaseFeesGate) { $structuralBranchPlanOnlyCommand } elseif ($liquiditySweepRejectedGate) { $fundingBasisPlanOnlyCommand } elseif ($fundingBlockedBySwarm) { $visibleWsCollectPreviewCommand } else { $visibleFundingCollectPreviewCommand }
$legacyVisibleCollectCommand = if ($spotPitEventForwardApprovalReadyGate) { $spotPitEventCollectCommand } elseif ($currentCrossVenueSpotClosureGate) { $structuralBranchPlanOnlyCommand } elseif ($forwardOosApprovalReadyGate) { $forwardOosCollectCommand } elseif ($slowLiquiditySelectedGate) { $slowLiquidityActivePlanOnlyCommand } elseif ($spotPerpBasisAvailabilityRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($spotPerpBasisSelectedGate) { $spotPerpBasisActivePlanOnlyCommand } elseif ($listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate) { $listingEventActiveAfterApprovalCommand } elseif ($crossVenueStructuralSelectedGate) { $crossVenueImplementationPlanOnlyCommand } elseif ($fundingRejectedBaseFeesGate) { $structuralBranchPlanOnlyCommand } elseif ($liquiditySweepRejectedGate) { $fundingBasisPlanOnlyCommand } elseif ($fundingBlockedBySwarm) { $visibleWsCollectCommand } else { $visibleFundingCollectCommand }
$legacyVisibleCollectPreviewShortcut = if ($spotPitEventForwardApprovalReadyGate -or $currentCrossVenueSpotClosureGate -or $forwardOosApprovalReadyGate -or $slowLiquiditySelectedGate -or $spotPerpBasisAvailabilityRejectedGate -or $spotPerpBasisSelectedGate -or $listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate -or $crossVenueStructuralSelectedGate -or $fundingRejectedBaseFeesGate -or $liquiditySweepRejectedGate) { "" } elseif ($fundingBlockedBySwarm) { $previewDenseWsShortcut } else { $preview7dFundingShortcut }
$legacyVisibleCollectConfirmedShortcut = if ($spotPitEventForwardApprovalReadyGate -or $currentCrossVenueSpotClosureGate -or $forwardOosApprovalReadyGate -or $slowLiquiditySelectedGate -or $spotPerpBasisAvailabilityRejectedGate -or $spotPerpBasisSelectedGate -or $listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate -or $crossVenueStructuralSelectedGate -or $fundingRejectedBaseFeesGate -or $liquiditySweepRejectedGate) { "" } elseif ($fundingBlockedBySwarm) { $startDenseWsShortcut } else { $start7dFundingShortcut }
$requiresUserApprovalForActualCollect = if ($currentCrossVenueSpotClosureGate) { $false } elseif ($spotPitEventForwardApprovalReadyGate -or $forwardOosApprovalReadyGate -or $listingEventHistoryCollectPreviewAwaitingApprovalGate -or $slowLiquidityHistoryDataPlanReadyGate) { $true } elseif ($slowLiquiditySelectedGate -or $spotPerpBasisAvailabilityRejectedGate -or $listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate -or $crossVenueStructuralSelectedGate -or $fundingRejectedBaseFeesGate -or $liquiditySweepRejectedGate) { $false } else { $true }
$visibleWsCollectRequiresUserApproval = [bool]($visibleWsCollectCommand -match "-ConfirmedLongRun")
$legacyVisibleCollectResolution = if ($spotPitEventForwardApprovalReadyGate) {
    "spot_pit_event_forward_awaiting_explicit_visible_confirmation"
} elseif ($currentCrossVenueSpotClosureGate) {
    "verified_cross_venue_spot_closure_select_new_structural_hypothesis_planonly"
} elseif ($forwardOosApprovalReadyGate) {
    "pit_linear_perp_forward_oos_awaiting_explicit_visible_confirmation"
} elseif ($slowLiquiditySelectedGate) {
    "slow_liquidity_regime_breakout_retest_planonly_selected_no_collect"
} elseif ($spotPerpBasisAvailabilityRejectedGate) {
    "spot_perp_basis_public_probe_rejected_select_next_non_hft_branch"
} elseif ($spotPerpBasisSelectedGate) {
    "spot_perp_basis_mean_reversion_planonly_selected_no_collect"
} elseif ($crossVenueStructuralSelectedGate) {
    "cross_venue_dislocation_planonly_selected_no_collect"
} elseif ($listingEventReplayRejectedGate) {
    "listing_event_replay_rejected_select_next_non_hft_branch"
} elseif ($listingEventReplayCandidateGate) {
    "listing_event_replay_candidate_requires_independent_validation"
} elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) {
    "listing_event_drift_reversal_planonly_after_cross_venue_rejected"
} elseif ($fundingRejectedBaseFeesGate) {
    "next_non_hft_structural_branch_planonly_after_funding_rejected_base_fees"
} elseif ($liquiditySweepRejectedGate) {
    "funding_basis_planonly_after_liquidity_sweep_rejected"
} elseif ($fundingBlockedBySwarm) {
    "redirected_to_ws_collect_because_funding_blocked_by_swarm"
} else {
    "funding_collect_current_branch"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    objective_focus = "prove_trading_edge_high_winrate_scheme_in_trading_mvp"
    objective_source_of_truth = "latest_user_scope_correction_plus_AGENTS_trading_edge_scope_rule"
    stale_internal_goal_handling = "If an older persistent goal mentions channel analysis, treat it as superseded context unless the user explicitly reopens channel work."
    channel_intake = if ($scopeFreezeRow) { $scopeFreezeRow.decision } else { "frozen_by_user_scope" }
    channel_intake_rule = if ($scopeFreezeRow) { $scopeFreezeRow.required_action } else { "Do not fetch, retry, monitor, or analyze new YouTube/RSS/transcript content unless explicitly reopened." }
    gate_status = $gate.status
    gate_warning = $gate.warning
    live_process_ids = @($gate.live_process_ids)
    completed_cycles = $gate.completed_cycles
    total_cycles = $gate.total_cycles
    gate_rows = $gate.rows
    gate_errors = $gate.errors
    funding_rows = if ($fundingRowsFromScorecard) { $fundingRowsFromScorecard } else { $gate.rows }
    funding_errors = if ($fundingErrorsFromScorecard) { $fundingErrorsFromScorecard } else { $gate.errors }
    strategies_scored = $scorecard.Count
    accepted_trading_strategies = $acceptedTradingRows.Count
    rejected_or_failed_strategies = $blockedRows.Count
    inconclusive_strategies = $inconclusiveRows.Count
    funding_current_verdict = if ($fundingRow) { $fundingRow.verdict } else { "not-specified" }
    funding_current_summary = if ($fundingBlockedBySwarm) { "$fundingSummaryFromScorecard; Рой L1/L2 decision=block" } elseif ($fundingRow) { $fundingRow.key_metric_summary } else { "not-specified" }
    primary_edge_candidate = if ($spotPitEventForwardApprovalReadyGate) { "MEXC/Gate spot PIT idiosyncratic crash-reclaim forward evidence collect" } elseif ($currentLeadLagClosureGate) { "Cross-sectional 4h capitulation rebound PlanOnly on existing spot history" } elseif ($currentCrossVenueSpotClosureGate) { "New structural hypothesis PlanOnly after verified MEXC/Gate spot rejection" } elseif ($forwardOosApprovalReadyGate) { "MEXC/Gate linear-perp cross-venue forward-OOS evidence collect" } elseif ($slowLiquidityFeatureNormalizerReadyGate) { "Slow liquidity feature normalizer ready for fixed replay validation" } elseif ($slowLiquidityFeatureNormalizerRejectedGate) { "Slow liquidity feature normalizer rejected insufficient fixed events" } elseif ($slowLiquidityFixedSignalReadyGate) { "Slow liquidity fixed v0 signal ready for feature normalizer" } elseif ($slowLiquidityHistoryQualityAcceptedGate) { "Slow liquidity history data-quality accepted; fixed signal PlanOnly needed" } elseif ($slowLiquidityHistoryDataPlanReadyGate) { "Slow liquidity history data plan awaiting explicit approval" } elseif ($slowLiquidityDataAvailabilityRejectedGate) { "Slow liquidity data availability rejected; history plan needed" } elseif ($slowLiquidityDataAvailabilityAcceptedGate) { "Slow liquidity data availability accepted; fixed signal PlanOnly needed" } elseif ($slowLiquiditySelectedGate) { "Slow liquidity regime breakout/retest PlanOnly" } elseif ($spotPerpBasisAvailabilityAwaitingProbeGate) { "Spot/perp basis availability public probe awaiting confirmation" } elseif ($spotPerpBasisAvailabilityRejectedGate) { "Spot/perp basis availability/public probe rejected; rescope branch" } elseif ($spotPerpBasisAvailabilityPreflightReadyGate) { "Spot/perp basis availability preflight PlanOnly" } elseif ($spotPerpBasisSelectedGate) { "Spot/perp basis mean-reversion PlanOnly research" } elseif ($listingEventReplayRejectedGate) { "New non-HFT structural branch PlanOnly after listing-event replay rejection" } elseif ($listingEventReplayCandidateGate) { "Listing event drift/reversal candidate needs independent validation" } elseif ($listingEventHistoryAvailabilityReadyGate) { "Listing event history availability public probe awaiting confirmation" } elseif ($listingEventHistoryAvailabilityAcceptedGate) { "Listing event history availability accepted; build collect approval packet" } elseif ($listingEventHistoryAvailabilityRejectedGate) { "Listing event history availability rejected; resample or fix Gate mapping" } elseif ($listingEventHistoryDataQualityRejectedGate) { "Listing event history data-quality rejected; run availability preflight" } elseif ($listingEventHistoryDataQualityPendingGate) { "Listing event history data-quality" } elseif ($listingEventNormalizerReadyGate) { "Listing event normalizer PlanOnly" } elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) { "Listing event OHLCV history collect preview awaiting approval" } elseif ($listingEventHistoryPlanReadyGate) { "Listing event OHLCV history collect preview PlanOnly" } elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) { "Listing event drift/reversal PlanOnly" } elseif ($crossVenueStructuralSelectedGate) { "Cross-venue spot dislocation inventory-rebalance PlanOnly" } elseif ($fundingRejectedBaseFeesGate) { "New non-HFT structural branch PlanOnly" } elseif ($liquiditySweepRejectedGate) { "Funding/basis carry structural PlanOnly diagnostics" } elseif ($fundingBlockedBySwarm -and $feeTierEvidencePresent) { "Funding fee-tier evidence validation" } elseif ($fundingBlockedBySwarm) { "Spot maker liquidity sweep/reversal event-quality proof tooling" } elseif ($primaryEdgeStep) { $primaryEdgeStep.action } else { "Prove or reject funding/basis carry on longer data" }
    primary_edge_status = if ($spotPitEventForwardApprovalReadyGate) { "spot_pit_event_forward_approval_packet_ready_awaiting_explicit_visible_confirmation" } elseif ($currentLeadLagClosureGate) { "cross_venue_lead_lag_verified_rejected_cross_sectional_capitulation_planonly_next" } elseif ($currentCrossVenueSpotClosureGate) { "cross_venue_spot_verified_rejected_select_new_structural_hypothesis_planonly" } elseif ($forwardOosApprovalReadyGate) { "forward_oos_approval_packet_ready_awaiting_explicit_visible_confirmation" } elseif ($slowLiquidityFeatureNormalizerReadyGate) { "slow_liquidity_feature_normalizer_ready_for_fixed_replay_validation" } elseif ($slowLiquidityFeatureNormalizerRejectedGate) { "slow_liquidity_feature_normalizer_rejected_insufficient_fixed_events" } elseif ($slowLiquidityFixedSignalReadyGate) { "slow_liquidity_fixed_signal_ready_for_feature_normalizer" } elseif ($slowLiquidityHistoryQualityAcceptedGate) { "slow_liquidity_history_quality_accepted_ready_for_fixed_signal_planonly" } elseif ($slowLiquidityHistoryDataPlanReadyGate) { "slow_liquidity_history_data_plan_ready_awaiting_explicit_approval" } elseif ($slowLiquidityDataAvailabilityRejectedGate) { "slow_liquidity_data_availability_rejected_needs_history_plan" } elseif ($slowLiquidityDataAvailabilityAcceptedGate) { "slow_liquidity_data_availability_accepted_ready_for_fixed_signal_planonly" } elseif ($slowLiquiditySelectedGate) { "slow_liquidity_regime_breakout_retest_planonly_ready_for_data_availability_preflight" } elseif ($spotPerpBasisAvailabilityAwaitingProbeGate) { "spot_perp_basis_availability_preflight_awaiting_public_probe_confirmation" } elseif ($spotPerpBasisAvailabilityRejectedGate) { "spot_perp_basis_public_probe_rejected_rescope" } elseif ($spotPerpBasisAvailabilityPreflightReadyGate) { "spot_perp_basis_availability_preflight_planonly_required" } elseif ($spotPerpBasisSelectedGate) { "spot_perp_basis_mean_reversion_planonly_research" } elseif ($listingEventReplayRejectedGate) { "listing_event_replay_rejected_select_next_branch" } elseif ($listingEventReplayCandidateGate) { "listing_event_replay_candidate_validate_independently" } elseif ($listingEventHistoryAvailabilityReadyGate) { "listing_event_history_availability_preflight_awaiting_public_probe_confirmation" } elseif ($listingEventHistoryAvailabilityAcceptedGate) { "listing_event_history_availability_preflight_accepted_build_collect_approval_packet" } elseif ($listingEventHistoryAvailabilityRejectedGate) { "listing_event_history_availability_preflight_rejected_resample_or_gate_fix" } elseif ($listingEventHistoryDataQualityRejectedGate) { "listing_event_history_data_quality_rejected_run_availability_preflight" } elseif ($listingEventHistoryDataQualityPendingGate) { "listing_event_history_data_quality_required" } elseif ($listingEventNormalizerReadyGate) { "listing_event_normalizer_planonly_ready" } elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) { "listing_event_history_collect_preview_awaiting_explicit_approval" } elseif ($listingEventHistoryPlanReadyGate) { "listing_event_history_collect_preview_planonly_ready" } elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) { "listing_event_drift_reversal_planonly_research" } elseif ($crossVenueStructuralSelectedGate) { "implement_cross_venue_dislocation_planonly_research" } elseif ($fundingRejectedBaseFeesGate) { "select_next_non_hft_structural_branch_planonly" } elseif ($liquiditySweepRejectedGate) { "funding_basis_carry_structural_planonly" } elseif ($fundingBlockedBySwarm -and $feeTierEvidencePresent) { "funding_blocked_validate_fee_evidence" } elseif ($fundingBlockedBySwarm) { "next_branch_spot_maker_liquidity_sweep_reversal" } elseif ($primaryEdgeStep) { $primaryEdgeStep.status } else { "needs_user_confirmation_for_visible_run" }
    funding_blocked_by_swarm = $fundingBlockedBySwarm
    liquidity_sweep_rejected_gate = $liquiditySweepRejectedGate
    funding_rejected_base_fees_gate = $fundingRejectedBaseFeesGate
    cross_venue_rejected_gate = $crossVenueRejectedGate
    current_cross_venue_spot_closure_gate = $currentCrossVenueSpotClosureGate
    current_cross_venue_lead_lag_closure_gate = $currentLeadLagClosureGate
    forward_oos_approval_ready_gate = $forwardOosApprovalReadyGate
    spot_pit_event_forward_approval_ready_gate = $spotPitEventForwardApprovalReadyGate
    forward_oos_plan_path = $forwardOosPlanPath
    listing_event_selected_gate = $listingEventSelectedGate
    listing_event_replay_rejected_gate = $listingEventReplayRejectedGate
    spot_perp_basis_selected_gate = $spotPerpBasisSelectedGate
    spot_perp_basis_availability_preflight_ready_gate = $spotPerpBasisAvailabilityPreflightReadyGate
    spot_perp_basis_availability_awaiting_probe_gate = $spotPerpBasisAvailabilityAwaitingProbeGate
    spot_perp_basis_availability_rejected_gate = $spotPerpBasisAvailabilityRejectedGate
    spot_perp_basis_rejected_gate = $spotPerpBasisRejectedGate
    listing_event_replay_candidate_gate = $listingEventReplayCandidateGate
    listing_event_normalizer_ready_gate = $listingEventNormalizerReadyGate
    listing_event_history_data_quality_pending_gate = $listingEventHistoryDataQualityPendingGate
    listing_event_history_data_quality_rejected_gate = $listingEventHistoryDataQualityRejectedGate
    listing_event_history_availability_ready_gate = $listingEventHistoryAvailabilityReadyGate
    listing_event_history_availability_accepted_gate = $listingEventHistoryAvailabilityAcceptedGate
    listing_event_history_availability_rejected_gate = $listingEventHistoryAvailabilityRejectedGate
    listing_event_history_plan_ready_gate = $listingEventHistoryPlanReadyGate
    listing_event_history_collect_preview_awaiting_approval_gate = $listingEventHistoryCollectPreviewAwaitingApprovalGate
    cross_venue_structural_selected_gate = $crossVenueStructuralSelectedGate
    slow_liquidity_regime_selected_gate = $slowLiquiditySelectedGate
    slow_liquidity_data_availability_ready_gate = $slowLiquidityDataAvailabilityReadyGate
    slow_liquidity_data_availability_accepted_gate = $slowLiquidityDataAvailabilityAcceptedGate
    slow_liquidity_data_availability_rejected_gate = $slowLiquidityDataAvailabilityRejectedGate
    slow_liquidity_history_data_plan_ready_gate = $slowLiquidityHistoryDataPlanReadyGate
    slow_liquidity_history_quality_accepted_gate = $slowLiquidityHistoryQualityAcceptedGate
    slow_liquidity_fixed_signal_ready_gate = $slowLiquidityFixedSignalReadyGate
    slow_liquidity_feature_normalizer_ready_gate = $slowLiquidityFeatureNormalizerReadyGate
    slow_liquidity_feature_normalizer_rejected_gate = $slowLiquidityFeatureNormalizerRejectedGate
    swarm_status = if ($swarmStatus) { [string]$swarmStatus.status } else { "NO_SWARM_STATUS" }
    swarm_limited = $swarmLimited
    swarm_independent_review_available = [bool]($swarmStatus -and [bool]$swarmStatus.independent_review_available)
    swarm_latest_workflow_id = $swarmLatestWorkflowId
    swarm_recommended_action = $swarmRecommendedAction
    fee_tier_evidence_present = $feeTierEvidencePresent
    current_cost_thresholds = @(
        $currentFundingThresholds | Select-Object scenario, round_trip_cost_bps, target_hold_intervals, required_funding_bps_per_interval_for_zero_net, observed_p95_funding_bps_per_interval, observed_p99_funding_bps_per_interval, observed_max_funding_bps_per_interval
    )
    master_index = $masterIndexPath
    edge_plan = $edgePlanPath
    edge_plan_csv = $edgePlanCsvPath
    scorecard = $scorecardPath
    funding_thresholds = $thresholdPath
    next_goal_step_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $nextGoalStepScript"
    edge_preflight_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $edgePreflightScript"
    swarm_status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json"
    trading_test_runner_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript -PlanOnly -Json"
    trading_test_full_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript"
    strategy_acceptance_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $strategyAcceptanceGateScript"
    funding_viability_gap_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingViabilityGapScript"
    funding_cost_assumption_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingCostAssumptionGateScript"
    funding_candidate_watchlist_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingCandidateWatchlistScript"
    funding_watchlist_review_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingWatchlistReviewScript"
    funding_basis_planonly_command = $fundingBasisPlanOnlyCommand
    structural_branch_planonly_command = $structuralBranchPlanOnlyCommand
    structural_branch_planonly_update_gate_command = $structuralBranchPlanOnlyUpdateGateCommand
    slow_liquidity_regime_planonly_command = $slowLiquidityPlanOnlyCommand
    slow_liquidity_regime_planonly_update_gate_command = $slowLiquidityPlanOnlyUpdateGateCommand
    slow_liquidity_data_availability_preflight_command = $slowLiquidityDataAvailabilityPreflightCommand
    slow_liquidity_data_availability_preflight_update_gate_command = $slowLiquidityDataAvailabilityPreflightUpdateGateCommand
    slow_liquidity_history_data_plan_command = $slowLiquidityHistoryPlanCommand
    slow_liquidity_history_data_plan_update_gate_command = $slowLiquidityHistoryPlanUpdateGateCommand
    slow_liquidity_fixed_signal_plan_command = $slowLiquidityFixedSignalPlanCommand
    slow_liquidity_fixed_signal_plan_update_gate_command = $slowLiquidityFixedSignalPlanUpdateGateCommand
    slow_liquidity_feature_normalizer_command = $slowLiquidityFeatureNormalizerCommand
    slow_liquidity_feature_normalizer_update_gate_command = $slowLiquidityFeatureNormalizerUpdateGateCommand
    spot_perp_basis_mean_reversion_planonly_command = $spotPerpBasisPlanOnlyCommand
    spot_perp_basis_availability_preflight_command = $spotPerpBasisAvailabilityPreflightCommand
    spot_perp_basis_availability_preflight_update_gate_command = $spotPerpBasisAvailabilityPreflightUpdateGateCommand
    spot_perp_basis_public_probe_plan_command = $spotPerpBasisPublicProbePlanCommand
    spot_perp_basis_public_probe_after_confirmation_command = $spotPerpBasisPublicProbeConfirmedCommand
    listing_event_planonly_command = $listingEventPlanOnlyCommand
    listing_event_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventPlanOnlyScript -UpdateGate -Json"
    listing_event_normalizer_planonly_command = $listingEventNormalizerPlanOnlyCommand
    listing_event_normalizer_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventNormalizerPlanOnlyScript -UpdateGate -Json"
    listing_event_history_planonly_command = $listingEventHistoryPlanOnlyCommand
    listing_event_history_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -UpdateGate -Json"
    listing_event_history_collect_preview_command = $listingEventHistoryCollectPreviewCommand
    listing_event_history_collect_preview_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectPreviewScript -UpdateGate -Json"
    listing_event_history_collect_approval_packet_command = $listingEventHistoryCollectApprovalPacketCommand
    listing_event_history_collect_visible_plan_command = $listingEventHistoryCollectVisiblePlanCommand
    listing_event_history_collect_visible_after_approval_command = $listingEventHistoryCollectVisibleCommand
    listing_event_history_data_quality_command = $listingEventHistoryDataQualityCommand
    listing_event_history_data_quality_update_gate_command = $listingEventHistoryDataQualityUpdateGateCommand
    listing_event_history_recollect_plan_command = $listingEventHistoryRecollectPlanCommand
    listing_event_history_availability_preflight_command = $listingEventHistoryAvailabilityPreflightCommand
    listing_event_history_availability_preflight_update_gate_command = $listingEventHistoryAvailabilityPreflightUpdateGateCommand
    listing_event_history_availability_public_probe_after_confirmation_command = $listingEventHistoryAvailabilityPublicProbeCommand
    branch_selector_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $branchSelectorScript"
    spot_pit_event_forward_approval_packet_path = $spotPitEventApprovalPacketPath
    spot_pit_event_forward_preview_command = $spotPitEventPreviewCommand
    spot_pit_event_forward_command_after_explicit_approval = $spotPitEventCollectCommand
    forward_oos_preview_command = $forwardOosPreviewCommand
    forward_oos_command_after_explicit_approval = $forwardOosCollectCommand
    sweep_reversal_acceptance_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $sweepReversalGateScript"
    visible_ws_collect_preview_command = $visibleWsCollectPreviewCommand
    visible_ws_collect_command = $visibleWsCollectCommand
    visible_ws_collect_command_resolution = $visibleWsCollectCommandResolution
    visible_ws_collect_requires_user_approval = $visibleWsCollectRequiresUserApproval
    requires_user_approval_for_actual_collect = $requiresUserApprovalForActualCollect
    visible_ws_collect_readiness_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectReadinessScript -Json"
    collect_approval_contract_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $collectApprovalContractScript -Json"
    ws_collect_approval_packet_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectApprovalPacketScript -Json"
    visible_ws_collect_plan_preview_latest = $visibleWsPlanPreviewLatest
    visible_ws_collect_preview_shortcut = $previewDenseWsShortcut
    visible_ws_collect_confirmed_shortcut = $startDenseWsShortcut
    research_goal_plan = $researchGoalPlanPath
    fee_tier_evidence = $feeTierEvidencePath
    public_fee_observations = $publicFeeObservationsPath
    funding_visible_collect_preview_command = $visibleFundingCollectPreviewCommand
    funding_visible_collect_command = $visibleFundingCollectCommand
    funding_visible_collect_preview_shortcut = $preview7dFundingShortcut
    funding_visible_collect_confirmed_shortcut = $start7dFundingShortcut
    visible_collect_command_legacy_resolution = $legacyVisibleCollectResolution
    visible_collect_preview_command = $legacyVisibleCollectPreviewCommand
    visible_collect_command = $legacyVisibleCollectCommand
    visible_collect_preview_shortcut = $legacyVisibleCollectPreviewShortcut
    visible_collect_confirmed_shortcut = $legacyVisibleCollectConfirmedShortcut
    final_review_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $finalReviewScript"
    next_allowed_action = $nextAllowedAction
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "trading_mvp Goal Status" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host ""

Write-Host "Focus" -ForegroundColor Yellow
Write-Host "  Objective focus: $($result.objective_focus)"
Write-Host "  Objective source: $($result.objective_source_of_truth)"
Write-Host "  Stale internal goal handling: $($result.stale_internal_goal_handling)"
Write-Host "  Channel intake: $($result.channel_intake)"
Write-Host "  Channel rule: $($result.channel_intake_rule)"
Write-Host ""

Write-Host "Gate" -ForegroundColor Yellow
Write-Host "  Status: $($result.gate_status)"
Write-Host "  Warning: $($result.gate_warning)"
Write-Host "  Live process ids: $(@($result.live_process_ids) -join ', ')"
Write-Host "  Cycles: $($result.completed_cycles)/$($result.total_cycles)"
Write-Host "  Funding rows/errors: $($result.funding_rows)/$($result.funding_errors)"
Write-Host ""

Write-Host "Strategy Scorecard" -ForegroundColor Yellow
Write-Host "  Strategies scored: $($result.strategies_scored)"
Write-Host "  Accepted trading strategies: $($result.accepted_trading_strategies)"
Write-Host "  Rejected/failed strategies: $($result.rejected_or_failed_strategies)"
Write-Host "  Inconclusive strategies: $($result.inconclusive_strategies)"
Write-Host "  Funding current verdict: $($result.funding_current_verdict)"
Write-Host "  Funding summary: $($result.funding_current_summary)"
Write-Host "  Primary edge candidate: $($result.primary_edge_candidate)"
Write-Host "  Primary edge status: $($result.primary_edge_status)"
Write-Host "  Funding blocked by swarm: $($result.funding_blocked_by_swarm)"
Write-Host "  Liquidity sweep rejected gate: $($result.liquidity_sweep_rejected_gate)"
Write-Host "  Swarm status: $($result.swarm_status)"
Write-Host "  Swarm limited: $($result.swarm_limited)"
Write-Host "  Swarm latest workflow: $($result.swarm_latest_workflow_id)"
Write-Host "  Swarm recommended action: $($result.swarm_recommended_action)"
Write-Host "  Fee-tier evidence present: $($result.fee_tier_evidence_present)"
Write-Host ""

Write-Host "Current Funding Cost Thresholds" -ForegroundColor Yellow
foreach ($row in $result.current_cost_thresholds) {
    Write-Host ("  hold={0} intervals: required={1} bps, observed p95={2}, p99={3}, max={4}" -f $row.target_hold_intervals, $row.required_funding_bps_per_interval_for_zero_net, $row.observed_p95_funding_bps_per_interval, $row.observed_p99_funding_bps_per_interval, $row.observed_max_funding_bps_per_interval)
}
Write-Host ""

Write-Host "Artifacts" -ForegroundColor Yellow
Write-Host "  Master index: $($result.master_index)"
Write-Host "  Edge plan: $($result.edge_plan)"
Write-Host "  Scorecard: $($result.scorecard)"
Write-Host "  Funding thresholds: $($result.funding_thresholds)"
Write-Host ""

Write-Host "Next Allowed Action" -ForegroundColor Yellow
Write-Host "  $($result.next_allowed_action)"
Write-Host ""
Write-Host "Next-step controller:"
Write-Host "  $($result.next_goal_step_command)"
Write-Host "Preflight command before next goal step:"
Write-Host "  $($result.edge_preflight_command)"
Write-Host "Swarm status command:"
Write-Host "  $($result.swarm_status_command)"
Write-Host "Trading test runner:"
Write-Host "  plan: $($result.trading_test_runner_command)"
Write-Host "  full: $($result.trading_test_full_command)"
Write-Host "Strategy acceptance gate:"
Write-Host "  $($result.strategy_acceptance_gate_command)"
Write-Host "Funding viability gap:"
Write-Host "  $($result.funding_viability_gap_command)"
Write-Host "Funding cost assumption gate:"
Write-Host "  $($result.funding_cost_assumption_gate_command)"
Write-Host "Funding candidate watchlist:"
Write-Host "  $($result.funding_candidate_watchlist_command)"
Write-Host "Funding watchlist review:"
Write-Host "  $($result.funding_watchlist_review_command)"
Write-Host "Funding/basis PlanOnly:"
Write-Host "  $($result.funding_basis_planonly_command)"
Write-Host "Structural branch PlanOnly:"
Write-Host "  $($result.structural_branch_planonly_command)"
Write-Host "Branch selector:"
Write-Host "  $($result.branch_selector_command)"
Write-Host "Sweep/reversal acceptance gate:"
Write-Host "  $($result.sweep_reversal_acceptance_gate_command)"
Write-Host "Visible WS collect preview for selected branch:"
Write-Host "  $($result.visible_ws_collect_preview_command)"
Write-Host "Visible WS collect readiness check before asking/starting:"
Write-Host "  $($result.visible_ws_collect_readiness_command)"
Write-Host "Visible WS collect approval contract before START72H:"
Write-Host "  $($result.collect_approval_contract_command)"
Write-Host "Visible WS collect approval packet before START72H:"
Write-Host "  $($result.ws_collect_approval_packet_command)"
Write-Host "Visible WS collect command, only after explicit approval:"
Write-Host "  $($result.visible_ws_collect_command)"
Write-Host "  requires approval: $($result.visible_ws_collect_requires_user_approval)"
Write-Host "Research goal plan:"
Write-Host "  $($result.research_goal_plan)"
Write-Host "Fee-tier evidence:"
Write-Host "  $($result.fee_tier_evidence)"
Write-Host "Public fee observations:"
Write-Host "  $($result.public_fee_observations)"
Write-Host "Legacy visible_collect resolution:"
Write-Host "  $($result.visible_collect_command_legacy_resolution)"
Write-Host "Legacy visible_collect preview:"
Write-Host "  $($result.visible_collect_preview_command)"
Write-Host "Legacy visible_collect command, only after explicit approval if it resolves to WS:"
Write-Host "  $($result.visible_collect_command)"
Write-Host "Funding collect preview, not the current primary branch after swarm block:"
Write-Host "  $($result.funding_visible_collect_preview_command)"
Write-Host "  shortcut: $($result.funding_visible_collect_preview_shortcut)"
Write-Host "Funding collect command, only after fee/economics branch is reopened and explicit approval:"
Write-Host "  $($result.funding_visible_collect_command)"
Write-Host "  shortcut: $($result.funding_visible_collect_confirmed_shortcut)"
Write-Host "Final review command, only after final manifest:"
Write-Host "  $($result.final_review_command)"

