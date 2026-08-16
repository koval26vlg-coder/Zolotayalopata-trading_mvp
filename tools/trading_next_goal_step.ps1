param(
    [switch]$Json,
    [string]$GatePath = "",
    [string]$ExactSlowLiquidityRecollectPlanPath = "",
    [string]$SprintReadinessPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$preflightScript = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$swarmStatusScript = Join-Path $repoRoot "tools\trading_swarm_status.ps1"
$tradingTestRunnerScript = Join-Path $repoRoot "tools\run_trading_tests.ps1"
$acceptanceGateScript = Join-Path $repoRoot "tools\trading_strategy_acceptance_gate.ps1"
$goalStatusScript = Join-Path $repoRoot "tools\trading_goal_status.ps1"
$visibleCollectScript = Join-Path $repoRoot "tools\start_funding_collect_visible.ps1"
$finalReviewScript = Join-Path $repoRoot "tools\run_funding_final_review_visible.ps1"
$fundingViabilityGapScript = Join-Path $repoRoot "tools\funding_viability_gap.ps1"
$fundingCostAssumptionGateScript = Join-Path $repoRoot "tools\funding_cost_assumption_gate.ps1"
$fundingCandidateWatchlistScript = Join-Path $repoRoot "tools\funding_candidate_watchlist.ps1"
$fundingWatchlistReviewScript = Join-Path $repoRoot "tools\funding_watchlist_review.ps1"
$fundingBasisPlanOnlyScript = Join-Path $repoRoot "tools\trading_funding_basis_planonly.ps1"
$structuralBranchPlanOnlyScript = Join-Path $repoRoot "tools\trading_structural_branch_planonly.ps1"
$newStructuralHypothesisPlanOnlyScript = Join-Path $repoRoot "tools\trading_new_structural_hypothesis_planonly.ps1"
$crossSectionalCapitulationPlanOnlyScript = Join-Path $repoRoot "tools\trading_cross_sectional_capitulation_planonly.ps1"
$pitUniverseSnapshotPreflightScript = Join-Path $repoRoot "tools\trading_pit_universe_snapshot_preflight_planonly.ps1"
$pitUniversePublicProbeScript = Join-Path $repoRoot "tools\trading_pit_universe_public_probe.ps1"
$pitUniverseCollectApprovalPacketScript = Join-Path $repoRoot "tools\trading_pit_universe_snapshot_collect_approval_packet.ps1"
$pitUniverseVisibleCollectScript = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"
$pitCrossVenueScreenVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_screen_visible.ps1"
$pitCrossVenueForwardOosVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_forward_oos_visible.ps1"
$spotPitEventForwardVisibleScript = Join-Path $repoRoot "tools\start_spot_pit_event_forward_visible.ps1"
$slowLiquidityPlanOnlyScript = Join-Path $repoRoot "tools\trading_slow_liquidity_regime_breakout_retest_planonly.ps1"
$slowLiquidityDataAvailabilityPreflightScript = Join-Path $repoRoot "tools\trading_slow_liquidity_data_availability_preflight.ps1"
$slowLiquidityHistoryDataPlanScript = Join-Path $repoRoot "tools\trading_slow_liquidity_history_data_plan.ps1"
$slowLiquidityFixedSignalPlanScript = Join-Path $repoRoot "tools\trading_slow_liquidity_fixed_signal_planonly.ps1"
$slowLiquidityFeatureNormalizerScript = Join-Path $repoRoot "tools\trading_slow_liquidity_feature_normalizer_planonly.ps1"
$slowLiquidityRescopePlanOnlyScript = Join-Path $repoRoot "tools\trading_slow_liquidity_rescope_planonly.ps1"
$slowLiquidityEventCensusScript = Join-Path $repoRoot "tools\trading_slow_liquidity_event_census_planonly.ps1"
$slowLiquidityFixedV1PlanScript = Join-Path $repoRoot "tools\trading_slow_liquidity_fixed_v1_planonly.ps1"
$slowLiquidityReplayV1Script = Join-Path $repoRoot "tools\trading_slow_liquidity_replay_v1_planonly.ps1"
$slowLiquidityExactRecollectStatusHelper = Join-Path $repoRoot "tools\slow_liquidity_exact_recollect_status.ps1"
$defaultSlowLiquidityExactRecollectPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
$defaultSlowLiquidityExactRecollectReadinessPath = Join-Path $repoRoot "docs\agent-log\readiness\one-week-historical-edge-sprint-readiness-20260812-v1.json"
$slowLiquidityExactRecollectLauncherScript = Join-Path $repoRoot "tools\start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
. $slowLiquidityExactRecollectStatusHelper
$spotPerpBasisPlanOnlyScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_mean_reversion_planonly.ps1"
$spotPerpBasisAvailabilityPreflightScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_availability_preflight.ps1"
$spotPerpBasisPublicProbeScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_public_probe.ps1"
$dailyMomentumSurvivorshipAuditScript = Join-Path $repoRoot "tools\trading_daily_momentum_survivorship_audit.ps1"
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
$defaultGatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$crossVenueFullOutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"
$visibleWsCollectScript = Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"
$wsCollectReadinessScript = Join-Path $repoRoot "tools\trading_ws_collect_readiness.ps1"
$collectApprovalContractScript = Join-Path $repoRoot "tools\trading_collect_approval_contract.ps1"
$wsCollectApprovalPacketScript = Join-Path $repoRoot "tools\trading_ws_collect_approval_packet.ps1"
$wsPostprocessScript = Join-Path $repoRoot "tools\run_ws_postprocess_visible.ps1"
$wsReplayValidationScript = Join-Path $repoRoot "tools\run_ws_replay_validation_visible.ps1"
$sweepReversalGateScript = Join-Path $repoRoot "tools\sweep_reversal_acceptance_gate.ps1"
$researchGoalPlanPath = Join-Path $repoRoot "docs\plans\2026-06-15-trading-mvp-research-goal.md"
$feeTierEvidencePath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_account_fee_tiers_current.json"
$publicFeeObservationsPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_public_fee_observations_20260627.json"
$preview7dFundingShortcut = Join-Path $repoRoot "TRADING_PREVIEW_7D_FUNDING.cmd"
$start7dFundingShortcut = Join-Path $repoRoot "TRADING_START_7D_FUNDING_CONFIRMED.cmd"
$previewDenseWsShortcut = Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"
$startDenseWsShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"

if ([string]::IsNullOrWhiteSpace($GatePath)) {
    $GatePath = $defaultGatePath
}
if ([string]::IsNullOrWhiteSpace($ExactSlowLiquidityRecollectPlanPath)) {
    $ExactSlowLiquidityRecollectPlanPath = $defaultSlowLiquidityExactRecollectPlanPath
}
if ([string]::IsNullOrWhiteSpace($SprintReadinessPath)) {
    $SprintReadinessPath = $defaultSlowLiquidityExactRecollectReadinessPath
}
$wsPostprocessShortcut = Join-Path $repoRoot "TRADING_WS_POSTPROCESS_FROM_GATE.cmd"
$visibleWsPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"
$visibleWsLegacyPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_6h_plan_preview_latest.json"
if ((-not (Test-Path -LiteralPath $visibleWsPlanPreviewLatest)) -and (Test-Path -LiteralPath $visibleWsLegacyPlanPreviewLatest)) {
    $visibleWsPlanPreviewLatest = $visibleWsLegacyPlanPreviewLatest
}

function Invoke-JsonScript {
    param([string]$Path)
    return (& pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -Json | ConvertFrom-Json)
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

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -GatePath $GatePath -Json | ConvertFrom-Json
$rawGate = Read-JsonFileOrNull -Path $gatePath
$slowLiquidityExactRecollectStatus = Get-SlowLiquidityExactRecollectStatus `
    -Gate $gate `
    -PlanPath $ExactSlowLiquidityRecollectPlanPath `
    -ReadinessPath $SprintReadinessPath `
    -DefaultLauncherPath $slowLiquidityExactRecollectLauncherScript `
    -RawGatePath $GatePath
$slowLiquidityExactRecollectCheckpointGate = [bool]$slowLiquidityExactRecollectStatus.checkpoint_relevant
$slowLiquidityExactRecollectPhase = [string]$slowLiquidityExactRecollectStatus.phase
$slowLiquidityExactRecollectAwaitingApprovalGate = [bool]$slowLiquidityExactRecollectStatus.awaiting_approval
$slowLiquidityExactRecollectIntegrityBlockedGate = [bool]$slowLiquidityExactRecollectStatus.integrity_blocked
$slowLiquidityExactRecollectStandingResearchGate = [bool]$slowLiquidityExactRecollectStatus.standing_research_authorized

if ($slowLiquidityExactRecollectCheckpointGate) {
    $phase = $slowLiquidityExactRecollectPhase
    $decision = switch ($phase) {
        "INTEGRITY_BLOCKED" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_INTEGRITY_BLOCKED"; break }
        "AWAITING_EXACT_APPROVAL" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_AWAITING_EXACT_APPROVAL"; break }
        "APPROVED_AWAITING_VISIBLE_LAUNCH" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_APPROVED_RUN_VISIBLE_ONCE"; break }
        "VISIBLE_LAUNCH_STARTING" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_VISIBLE_LAUNCH_STARTING_STATUS_ONLY"; break }
        "RUNNING" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_RUNNING_STATUS_ONLY"; break }
        "READY_FOR_TECHNICAL_QUALITY" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_RUN_TECHNICAL_QUALITY_ONLY"; break }
        "TECHNICAL_QUALITY_COMMITTING" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_TECHNICAL_QUALITY_COMMITTING_STATUS_ONLY"; break }
        "STOPPED_INCOMPLETE_NO_RETRY" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_STOPPED_INCOMPLETE_NO_RETRY"; break }
        "QUALITY_ACCEPTED_CONTINUE_STANDING_PUBLIC_RESEARCH" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_CONTINUE_STANDING_PUBLIC_RESEARCH"; break }
        "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL"; break }
        "QUALITY_REJECTED_TERMINAL_NO_RETRY" { "SLOW_LIQUIDITY_EXACT_RECOLLECT_QUALITY_REJECTED_TERMINAL_NO_RETRY"; break }
        default { "SLOW_LIQUIDITY_EXACT_RECOLLECT_INTEGRITY_BLOCKED" }
    }
    $allowedActions = switch ($phase) {
        "INTEGRITY_BLOCKED" { @("inspect_exact_slow_liquidity_recollect_binding", "repair_immutable_lifecycle_binding"); break }
        "AWAITING_EXACT_APPROVAL" { @("await_exact_hash_bound_slow_liquidity_recollect_approval", "read_current_exact_approval_packet", "run_non_starting_approval_freeze_preflight", "quick_status_checks"); break }
        "APPROVED_AWAITING_VISIBLE_LAUNCH" { @("run_single_exact_visible_public_read_only_launch", "quick_status_checks"); break }
        "VISIBLE_LAUNCH_STARTING" { @("exact_status_check", "exact_stop"); break }
        "RUNNING" { @("exact_status_check", "exact_stop"); break }
        "READY_FOR_TECHNICAL_QUALITY" { @("run_exact_technical_quality_preflight", "run_exact_technical_quality"); break }
        "TECHNICAL_QUALITY_COMMITTING" { @("exact_status_check"); break }
        "STOPPED_INCOMPLETE_NO_RETRY" { @("exact_status_check"); break }
        "QUALITY_ACCEPTED_CONTINUE_STANDING_PUBLIC_RESEARCH" { @("continue_same_scope_public_research", "run_next_bounded_public_research_step", "official_identity_discovery", "exact_status_check"); break }
        "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL" { @("await_exact_official_asset_identity_verification_approval", "exact_status_check"); break }
        "QUALITY_REJECTED_TERMINAL_NO_RETRY" { @("exact_status_check"); break }
        default { @("exact_status_check") }
    }
    $blockedActions = @(
        "hidden_or_second_collector",
        "evaluator",
        "oos",
        "returns_or_pnl",
        "grid_or_retune",
        "execution_probe",
        "paper_or_live",
        "private_api_or_real_capital",
        "leverage_or_margin",
        "identity_scope_change_without_new_checkpoint"
    )
    if ($phase -eq "AWAITING_EXACT_APPROVAL") {
        $blockedActions += @("collector_before_exact_approval", "launch_record_or_output_before_exact_approval")
    }
    if ($phase -eq "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL") {
        $blockedActions += "official_identity_without_separate_exact_approval"
    }
    if ($phase -in @("VISIBLE_LAUNCH_STARTING", "RUNNING")) {
        $blockedActions += @("duplicate_owner", "second_writer", "consumer_of_incomplete_output")
    }
    if ($phase -in @("STOPPED_INCOMPLETE_NO_RETRY", "QUALITY_REJECTED_TERMINAL_NO_RETRY")) {
        $blockedActions += @("resume", "retry", "rescope_without_new_exact_approval")
    }
    if ($phase -eq "INTEGRITY_BLOCKED") {
        $blockedActions += @("receipt_or_launch_with_invalid_binding", "quality_with_invalid_binding")
    }

    $primaryCommand = if ($slowLiquidityExactRecollectIntegrityBlockedGate) {
        "blocked: repair exact slow-liquidity lifecycle binding"
    } else {
        [string]$slowLiquidityExactRecollectStatus.primary_command
    }
    $legacyVisibleCollectCommand = if ($phase -eq "AWAITING_EXACT_APPROVAL") {
        [string]$slowLiquidityExactRecollectStatus.preflight_command
    } else {
        $primaryCommand
    }
    $resolution = if ($phase -eq "AWAITING_EXACT_APPROVAL") {
        "slow_liquidity_exact_recollect_awaiting_exact_hash_bound_approval"
    } else {
        "slow_liquidity_exact_recollect_$($phase.ToLowerInvariant())"
    }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        decision = $decision
        reason = if ($slowLiquidityExactRecollectIntegrityBlockedGate) {
            "The exact slow-liquidity lifecycle failed closed because its immutable bindings do not match."
        } else {
            [string]$slowLiquidityExactRecollectStatus.next_action
        }
        allowed_actions = @($allowedActions)
        blocked_actions = @($blockedActions)
        requires_user_approval = [bool]$slowLiquidityExactRecollectStatus.requires_user_approval
        requires_user_approval_for_actual_collect = $slowLiquidityExactRecollectAwaitingApprovalGate
        required_user_input = [string]$slowLiquidityExactRecollectStatus.required_user_input
        standing_research_authorized = [bool]$slowLiquidityExactRecollectStatus.standing_research_authorized
        standing_research_scope_binding_valid = [bool]$slowLiquidityExactRecollectStatus.standing_research_scope_binding_valid
        standing_research_continue_allowed = [bool]$slowLiquidityExactRecollectStatus.standing_research_continue_allowed
        standing_research_policy_file_sha256 = [string]$slowLiquidityExactRecollectStatus.standing_research_policy_file_sha256
        primary_command = $primaryCommand
        state = [ordered]@{
            gate_status = [string]$gate.status
            run_id = [string]$gate.run_id
            replay_allowed = $false
            grid_allowed = $false
            paper_forward_allowed = $false
            live_orders = $false
            strategy_accepted = $false
            slow_liquidity_exact_recollect_checkpoint_gate = $true
            slow_liquidity_exact_recollect_phase = $phase
            slow_liquidity_exact_recollect_awaiting_approval_gate = $slowLiquidityExactRecollectAwaitingApprovalGate
            slow_liquidity_exact_recollect_integrity_blocked_gate = $slowLiquidityExactRecollectIntegrityBlockedGate
            slow_liquidity_exact_recollect_standing_research_authorized = $slowLiquidityExactRecollectStandingResearchGate
            slow_liquidity_exact_recollect_standing_research_scope_binding_valid = [bool]$slowLiquidityExactRecollectStatus.standing_research_scope_binding_valid
            slow_liquidity_exact_recollect_standing_research_policy_file_sha256 = [string]$slowLiquidityExactRecollectStatus.standing_research_policy_file_sha256
            slow_liquidity_exact_recollect_receipt_present = [bool]$slowLiquidityExactRecollectStatus.receipt_present
            slow_liquidity_exact_recollect_launch_record_present = [bool]$slowLiquidityExactRecollectStatus.launch_record_present
            slow_liquidity_exact_recollect_output_present = [bool]$slowLiquidityExactRecollectStatus.output_present
            slow_liquidity_exact_recollect_manifest_present = [bool]$slowLiquidityExactRecollectStatus.manifest_present
            slow_liquidity_exact_recollect_quality_output_present = [bool]$slowLiquidityExactRecollectStatus.quality_output_present
            slow_liquidity_exact_recollect_errors = @($slowLiquidityExactRecollectStatus.errors)
        }
        commands = [ordered]@{
            slow_liquidity_exact_recollect_preflight = [string]$slowLiquidityExactRecollectStatus.preflight_command
            slow_liquidity_exact_recollect_approval_packet = [string]$slowLiquidityExactRecollectStatus.approval_packet_command
            slow_liquidity_exact_recollect_launch = [string]$slowLiquidityExactRecollectStatus.launch_command
            slow_liquidity_exact_recollect_status = [string]$slowLiquidityExactRecollectStatus.status_command
            slow_liquidity_exact_recollect_stop = [string]$slowLiquidityExactRecollectStatus.stop_command
            slow_liquidity_exact_recollect_quality_preflight = [string]$slowLiquidityExactRecollectStatus.quality_preflight_command
            slow_liquidity_exact_recollect_quality = [string]$slowLiquidityExactRecollectStatus.quality_command
            visible_collect_legacy_resolution = $resolution
            visible_collect_preview = $legacyVisibleCollectCommand
            visible_collect_after_approval = $legacyVisibleCollectCommand
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -GatePath `"$GatePath`" -Json"
        }
        fast_path = [ordered]@{
            reason = "exact_slow_liquidity_lifecycle_is_current"
            phase = $phase
            raw_gate_path = $GatePath
            heavy_checks_skipped = @($preflightScript, $acceptanceGateScript, $goalStatusScript, $sweepReversalGateScript, $swarmStatusScript)
        }
    }
    if ($Json) {
        $result | ConvertTo-Json -Depth 12
        exit 0
    }
    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Phase: $phase"
    Write-Host "Next: $($result.reason)"
    Write-Host "Command: $primaryCommand"
    exit 0
}

$spotPitEventForwardApprovalReady = [string]$gate.next_goal_decision -eq "SPOT_PIT_EVENT_FORWARD_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"
if ($spotPitEventForwardApprovalReady) {
    $packetPath = [string]$rawGate.spot_pit_event_forward_approval_packet_path
    $primaryCommand = [string]$gate.command_after_explicit_approval
    $planOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$spotPitEventForwardVisibleScript`" -ApprovalPacketPath `"$packetPath`" -PlanOnly -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = "SPOT_PIT_EVENT_FORWARD_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION"
        reason = "Existing-data fixed branches were exhausted without an accepted edge. The next independent hypothesis is sealed before future data, all readiness checks pass, and the visible collector has 2h data-quality plus 48h futility gates. This is evidence collection, not a strategy claim."
        requires_user_approval = $true
        requires_user_approval_for_actual_collect = $true
        primary_command = $primaryCommand
        allowed_actions = @("inspect_sealed_approval_packet", "run_planonly_preview", "await_explicit_visible_collect_confirmation", "run_gate_status_checks")
        blocked_actions = @("automatic_collect_start", "hidden_or_background_collect", "threshold_tuning", "replay", "grid_search", "paper_forward", "live_orders", "api_keys", "leverage_or_margin")
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            branch = "spot_pit_idiosyncratic_crash_reclaim_1m"
            approval_packet_path = $packetPath
            strategy_accepted = $false
            replay_allowed = $false
            grid_allowed = $false
            paper_forward_allowed = $false
            live_orders = $false
            swarm = "cancelled_by_user_manual_codex_control"
        }
        commands = [ordered]@{
            planonly_preview = $planOnlyCommand
            after_explicit_approval = $primaryCommand
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        fast_path = [ordered]@{ reason = "spot_pit_event_forward_approval_packet_is_current"; raw_gate_path = $gatePath }
    }
    if ($Json) { $result | ConvertTo-Json -Depth 12; exit 0 }
    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Requires explicit confirmation: true"
    Write-Host "Preview: $planOnlyCommand"
    exit 0
}
$leadLagClosureCurrent = (
    [string]$gate.next_goal_decision -eq "CROSS_VENUE_SPOT_LEAD_LAG_VERIFIED_REJECTED_SELECT_NEW_STRUCTURAL_HYPOTHESIS_PLANONLY" -and
    $rawGate -and
    [string]$rawGate.last_cross_venue_lead_lag_audit_decision -eq "CROSS_VENUE_SPOT_LEAD_LAG_VERIFIED_REJECTED_NO_FIXED_SIGNALS"
)
if ($leadLagClosureCurrent) {
    $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$crossSectionalCapitulationPlanOnlyScript`" -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = "CROSS_VENUE_SPOT_LEAD_LAG_CLOSED_SELECT_CROSS_SECTIONAL_CAPITULATION_PLANONLY"
        reason = "The sealed 51.28-million-row lead/lag full scan was independently audited and produced zero signals across 12 matched bases. Do not lower thresholds on the same sample. The next distinct existing-data branch is slow 4h cross-sectional capitulation rebound with fixed base-cost gates."
        requires_user_approval = $false
        requires_user_approval_for_actual_collect = $false
        primary_command = $primaryCommand
        allowed_actions = @(
            "preserve_verified_lead_lag_rejection",
            "seal_cross_sectional_capitulation_planonly",
            "use_existing_slow_liquidity_4h_spot_history_only",
            "keep_manual_codex_control_after_user_cancelled_swarm"
        )
        blocked_actions = @(
            "lower_lead_lag_thresholds_on_same_sample",
            "grid_search",
            "new_collect",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin"
        )
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            closed_branch = "cross_venue_spot_lead_lag_spillover"
            branch_verdict = "verified_rejected_no_fixed_signals"
            audit_path = [string]$rawGate.last_cross_venue_lead_lag_audit_path
            selected_branch = "cross_sectional_capitulation_rebound_4h_spot"
            strategy_accepted = $false
            replay_allowed = $false
            grid_allowed = $false
            paper_forward_allowed = $false
            live_orders = $false
        }
        commands = [ordered]@{
            cross_sectional_capitulation_planonly = $primaryCommand
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        fast_path = [ordered]@{
            reason = "verified_lead_lag_closure_is_current"
            raw_gate_path = $gatePath
        }
    }
    if ($Json) { $result | ConvertTo-Json -Depth 12; exit 0 }
    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Command: $primaryCommand"
    exit 0
}
$crossVenueSpotClosureCurrent = (
    [string]$gate.next_goal_decision -eq "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH" -and
    $rawGate -and
    [string]$rawGate.last_cross_venue_spot_full_scan_audit_decision -eq "CROSS_VENUE_SPOT_FULL_SCAN_VERIFIED_REJECTED_NO_NET_EDGE_AFTER_BASE_COSTS"
)
if ($crossVenueSpotClosureCurrent) {
    $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$structuralBranchPlanOnlyScript`" -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = "CROSS_VENUE_SPOT_BRANCH_CLOSED_SELECT_NEW_STRUCTURAL_HYPOTHESIS_PLANONLY"
        reason = "The completed clean-slice full scan passed a fail-closed evidence audit and found zero eligible spot dislocations. The best >=25 USDT-capacity gross edge was 46.7189 bps versus 49 bps fees plus slippage and 69 bps fixed total cost. Do not rerun or tune this branch."
        requires_user_approval = $false
        requires_user_approval_for_actual_collect = $false
        primary_command = $primaryCommand
        allowed_actions = @(
            "preserve_verified_spot_branch_rejection",
            "run_structural_branch_planonly",
            "select_new_hypothesis_using_existing_data_first",
            "keep_manual_codex_control_after_user_cancelled_swarm"
        )
        blocked_actions = @(
            "repeat_identical_cross_venue_spot_full_scan",
            "grid_tune_rejected_spot_branch",
            "oos_or_walk_forward_after_failed_economics_screen",
            "new_collect_without_separate_gate",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin"
        )
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            gate_next_goal_decision = $gate.next_goal_decision
            selected_branch = $null
            closed_branch = "cross_venue_spot_dislocation_inventory_rebalance"
            branch_verdict = "verified_rejected_no_net_edge_after_base_costs"
            audit_path = [string]$rawGate.last_cross_venue_spot_full_scan_audit_path
            audit_sha256 = [string]$rawGate.last_cross_venue_spot_full_scan_audit_sha256
            strategy_accepted = $false
            replay_allowed = $false
            grid_allowed = $false
            paper_forward_allowed = $false
            live_orders = $false
        }
        commands = [ordered]@{
            structural_branch_planonly = $primaryCommand
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        fast_path = [ordered]@{
            reason = "verified_cross_venue_spot_closure_is_current"
            raw_gate_path = $gatePath
        }
    }
    if ($Json) {
        $result | ConvertTo-Json -Depth 12
        exit 0
    }
    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Command: $primaryCommand"
    exit 0
}
$forwardOosApprovalReady = [string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"
if ($forwardOosApprovalReady) {
    $primaryCommand = if ($gate.command_after_explicit_approval) {
        [string]$gate.command_after_explicit_approval
    } else {
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueForwardOosVisibleScript`" -PlanPath `"$($rawGate.forward_oos_plan_path)`" -ConfirmedForwardOosCollect"
    }
    $planOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueForwardOosVisibleScript`" -PlanPath `"$($rawGate.forward_oos_plan_path)`" -PlanOnly -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION"
        reason = "The one-shot public probe preserved all 26 discovery bases, found an 18-base provisional identity universe and at least one cost-positive stress observation. This only justifies a sealed forward-OOS data collect, not a strategy claim."
        requires_user_approval = $true
        requires_user_approval_for_actual_collect = $true
        primary_command = $primaryCommand
        allowed_actions = @(
            "inspect_forward_oos_planonly",
            "await_explicit_visible_collect_confirmation",
            "run_gate_status_checks"
        )
        blocked_actions = @(
            "automatic_collect_start",
            "count_failed_attempts_as_valid_cycles",
            "overwrite_attempt_segments",
            "reuse_discovery_as_oos",
            "replay",
            "backtest",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin"
        )
        state = [ordered]@{
            gate_status = $gate.status
            gate_next_goal_decision = $gate.next_goal_decision
            selected_branch = "pit_linear_perp_cross_venue_forward_oos"
            supports_spot_objective = $false
            prior_spot_branch_rejected = $true
            plan_path = if ($rawGate) { $rawGate.forward_oos_plan_path } else { $null }
            plan_sha256 = if ($rawGate) { $rawGate.forward_oos_plan_sha256 } else { $null }
            target_valid_cycles = if ($rawGate -and $rawGate.strategy_branch_status) { $rawGate.strategy_branch_status.target_valid_cycles } else { 800 }
            min_valid_pairs_per_cycle = if ($rawGate -and $rawGate.strategy_branch_status) { $rawGate.strategy_branch_status.min_valid_pairs_per_cycle } else { 14 }
            strategy_accepted = $false
            replay_allowed = $false
            live_orders = $false
        }
        commands = [ordered]@{
            planonly = $planOnlyCommand
            command_after_explicit_approval = $primaryCommand
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        fast_path = [ordered]@{ reason = "forward_oos_approval_packet_ready"; raw_gate_path = $gatePath }
    }
    if ($Json) { $result | ConvertTo-Json -Depth 12; exit 0 }
    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Explicit confirmation required: True"
    Write-Host "Command after confirmation: $primaryCommand"
    exit 0
}
$pitLinearPerpScreenReady = [string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"
if ($pitLinearPerpScreenReady) {
    $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueScreenVisibleScript`" -ConfirmedResearchScreen -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"
        reason = "The old spot branch is already rejected after base costs. The PIT source is linear_perp only; the sole allowed step is a separately labelled visible streaming screen through the immutable clean-slice mask."
        requires_user_approval = $false
        requires_user_approval_for_actual_collect = $false
        primary_command = $primaryCommand
        allowed_actions = @(
            "run_visible_streaming_linear_perp_screen",
            "verify_clean_slice_source_and_mask_hashes",
            "report_fixed_base_cost_hurdle_without_pnl_claim",
            "keep_strategy_unaccepted"
        )
        blocked_actions = @(
            "interpret_as_spot_scan",
            "materialize_filtered_jsonl",
            "new_collect",
            "replay",
            "backtest",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin"
        )
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            gate_next_goal_decision = $gate.next_goal_decision
            gate_replay_allowed = $gate.replay_allowed
            selected_branch = "pit_linear_perp_cross_venue_screening"
            source_contract_type = "linear_perp"
            supports_spot_objective = $false
            prior_spot_branch_rejected = $true
            clean_slice_spec_path = if ($rawGate) { $rawGate.last_pit_two_venue_clean_slice_spec_path } else { $null }
            mask_sha256 = if ($rawGate) { $rawGate.last_pit_two_venue_clean_slice_mask_sha256 } else { $null }
            strategy_accepted = $false
            live_orders = $false
            channel_intake = "blocked"
        }
        commands = [ordered]@{
            visible_screen = $primaryCommand
            visible_screen_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueScreenVisibleScript`" -PlanOnly -Json"
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        fast_path = [ordered]@{
            reason = "pit_clean_slice_linear_perp_screen_ready"
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }
    if ($Json) {
        $result | ConvertTo-Json -Depth 10
        exit 0
    }
    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Primary command: $primaryCommand"
    exit 0
}
$spotPerpBasisAwaitingPublicProbeFastPath = (
    ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE") -and
    [bool]$gate.requires_explicit_user_approval_for_public_probe
)

if ($spotPerpBasisAwaitingPublicProbeFastPath) {
    $spotPerpBasisPublicProbePlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -UpdateGate -Json"
    $spotPerpBasisPublicProbeConfirmedCommand = if ($gate.command_after_explicit_approval) { [string]$gate.command_after_explicit_approval } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json" }
    $decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION"
    $reason = "spot/perp basis availability preflight is ready for a short visible public REST probe, but explicit user confirmation is required. No collect, replay, grid, live orders, API keys, leverage, margin or paper-forward."
    $allowedActions = @(
        "await_explicit_confirmation_for_short_public_spot_perp_availability_probe",
        "read_command_after_explicit_approval",
        "block_collect_grid_replay_live_api_and_paper_forward",
        "keep_funding_as_risk_filter_not_pnl_source"
    )
    $blockedActions = @(
        "actual_collect_without_explicit_confirmation",
        "replay",
        "grid_search",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward_without_accepted_research",
        "winrate_claim_without_expectancy_net_pnl_oos_walk_stress"
    )
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = $decision
        reason = $reason
        requires_user_approval = $true
        requires_user_approval_for_actual_collect = $true
        primary_command = "await explicit confirmation; then run command_after_explicit_approval"
        command_after_explicit_approval = $spotPerpBasisPublicProbeConfirmedCommand
        allowed_actions = $allowedActions
        blocked_actions = $blockedActions
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            gate_completed_cycles = $gate.completed_cycles
            gate_total_cycles = $gate.total_cycles
            gate_rows = $gate.rows
            gate_errors = $gate.errors
            gate_warning = $gate.warning
            gate_next_step_after_ready = $gate.next_step_after_ready
            gate_raw_next_step_after_ready = $gate.raw_gate_next_step_after_ready
            gate_postprocess_block = $gate.postprocess_block
            gate_next_goal_decision = $gate.next_goal_decision
            gate_replay_allowed = $gate.replay_allowed
            primary_output_complete = $gate.primary_output_complete
            expected_outputs_complete = $gate.expected_outputs_complete
            preflight_status = "skipped_fast_path"
            preflight_ok = $null
            preflight_fail_count = $null
            preflight_warn_count = $null
            acceptance_stage = "skipped_fast_path"
            strategy_accepted = $false
            live_orders = $false
            sweep_reversal_gate_accepted = $false
            sweep_reversal_gate_decision = "skipped_fast_path"
            sweep_reversal_gate_fail_count = $null
            sweep_reversal_gate_reasons = @()
            objective_focus = "trading_mvp edge proof"
            objective_source_of_truth = "active-run-gate"
            stale_internal_goal_handling = "ignore_stale_goal_when_gate_has_branch_decision"
            channel_intake = "blocked"
            accepted_trading_strategies = @()
            primary_edge_status = "spot_perp_basis_availability_preflight_awaiting_public_probe_confirmation"
            funding_blocked_by_swarm = $false
            liquidity_sweep_rejected_gate = $false
            funding_rejected_base_fees_gate = $false
            cross_venue_rejected_gate = $true
            listing_event_selected_gate = $false
            listing_event_replay_rejected_gate = $true
            spot_perp_basis_selected_gate = $true
            spot_perp_basis_availability_preflight_ready_gate = $false
            spot_perp_basis_availability_awaiting_probe_gate = $true
            spot_perp_basis_availability_rejected_gate = $false
            listing_event_replay_candidate_gate = $false
            listing_event_normalizer_ready_gate = $false
            listing_event_history_data_quality_pending_gate = $false
            listing_event_history_data_quality_rejected_gate = $false
            listing_event_history_availability_ready_gate = $false
            listing_event_history_availability_accepted_gate = $false
            listing_event_history_availability_rejected_gate = $false
            listing_event_history_plan_ready_gate = $false
            listing_event_history_collect_preview_awaiting_approval_gate = $false
            cross_venue_structural_selected_gate = $false
            swarm_status = "SKIPPED_FAST_PATH"
            swarm_limited = $false
            swarm_independent_review_available = $false
            swarm_latest_workflow_id = ""
            swarm_recommended_action = "not_needed_for_status_fast_path"
            fee_tier_evidence_present = Test-Path -LiteralPath $feeTierEvidencePath
        }
        commands = [ordered]@{
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
            spot_perp_basis_public_probe_plan = $spotPerpBasisPublicProbePlanCommand
            spot_perp_basis_public_probe_after_confirmation = $spotPerpBasisPublicProbeConfirmedCommand
            visible_collect_preview = $spotPerpBasisPublicProbePlanCommand
            visible_collect_after_approval = $spotPerpBasisPublicProbePlanCommand
            branch_selector = "pwsh -NoProfile -ExecutionPolicy Bypass -File $branchSelectorScript"
            research_goal_plan = $researchGoalPlanPath
            fee_tier_evidence = $feeTierEvidencePath
        }
        fast_path = [ordered]@{
            reason = "active_gate_already_requires_explicit_public_probe_confirmation"
            skipped_scripts = @(
                $preflightScript,
                $acceptanceGateScript,
                $goalStatusScript,
                $sweepReversalGateScript,
                $swarmStatusScript
            )
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 8
        exit 0
    }

    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Decision: $decision"
    Write-Host "Reason: $reason"
    Write-Host "Requires explicit approval: True"
    Write-Host "Command after explicit approval:"
    Write-Host "  $spotPerpBasisPublicProbeConfirmedCommand"
    exit 0
}

$dailyMomentumCandidateFastPath = (
    ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_RESEARCH_CANDIDATE_REQUIRES_INDEPENDENT_BIAS_REVIEW") -or
    ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_RESEARCH_CANDIDATE_REQUIRES_SURVIVORSHIP_AUDIT") -or
    ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_REVISE_GATES_FAILED") -or
    ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_REVISE_REQUIRED") -or
    ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_READY_FOR_INDEPENDENT_REVIEW") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "cross_sectional_momentum_daily" -and
        [string]$gate.strategy_branch_status.verdict -in @(
            "research_candidate_requires_independent_bias_review",
            "research_candidate_requires_survivorship_audit",
            "research_candidate_revise_gates_failed",
            "survivorship_audit_revise_required",
            "survivorship_audit_ready_for_independent_review"
        )
    )
)

if ($dailyMomentumCandidateFastPath) {
    $auditRevise = ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_REVISE_REQUIRED") -or (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.verdict -eq "survivorship_audit_revise_required"
    )
    $decision = if ($auditRevise) { "DAILY_CROSS_SECTIONAL_MOMENTUM_ACCEPTANCE_BLOCKED_BY_SURVIVORSHIP_AND_RISK" } else { "DAILY_CROSS_SECTIONAL_MOMENTUM_CANDIDATE_REQUIRES_SURVIVORSHIP_AUDIT" }
    $reason = if ($auditRevise) { "daily cross-sectional momentum numeric edge remains insufficient for acceptance: survivorship/point-in-time universe is not controlled, some market histories are too short, and the non-Binance baseline fails max-drawdown policy. Do not paper-forward/live/API/grid." } else { "daily cross-sectional momentum has positive numeric OOS/rolling-walk-forward/stress evidence under base/VIP0 costs, but it is not an accepted strategy until survivorship bias, point-in-time universe quality, drawdown policy and live long/short perp assumptions are resolved." }
    $allowedActions = if ($auditRevise) {
        @(
            "accept_daily_momentum_as_not_accepted_due_survivorship_and_risk",
            "source_point_in_time_delisted_universe_only_after_explicit_collect_approval",
            "select_new_research_hypothesis_planonly",
            "block_collect_grid_replay_live_api_and_paper_forward"
        )
    } else {
        @(
            "build_survivorship_point_in_time_universe_audit",
            "build_daily_momentum_survivorship_bias_audit",
            "harden_drawdown_concentration_and_funding_drag_gates",
            "block_collect_grid_replay_live_api_and_paper_forward"
        )
    }
    $blockedActions = @(
        "paper_forward_without_bias_review",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "grid_search",
        "winrate_claim_without_expectancy_net_pnl_oos_walk_stress",
        "tuning_rejected_slow_liquidity_or_spot_perp_branches"
    )
    $reportPath = if ($rawGate -and $rawGate.PSObject.Properties.Name -contains "last_daily_momentum_backtest_output_path") { [string]$rawGate.last_daily_momentum_backtest_output_path } else { "" }
    $validationPath = if ($rawGate -and $rawGate.PSObject.Properties.Name -contains "last_daily_momentum_validation_output_path") { [string]$rawGate.last_daily_momentum_validation_output_path } else { "" }
    $survivorshipAuditPath = if ($rawGate -and $rawGate.PSObject.Properties.Name -contains "last_daily_momentum_survivorship_audit_output_path") { [string]$rawGate.last_daily_momentum_survivorship_audit_output_path } else { "" }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = $decision
        reason = $reason
        requires_user_approval = $false
        requires_user_approval_for_actual_collect = $false
        primary_command = if ($auditRevise) { "select new PlanOnly hypothesis or explicitly approve point-in-time/delisted universe sourcing; do not collect/grid/live/API by default" } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $dailyMomentumSurvivorshipAuditScript -UpdateGate -Json" }
        allowed_actions = $allowedActions
        blocked_actions = $blockedActions
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            gate_rows = $gate.rows
            gate_errors = $gate.errors
            gate_next_goal_decision = $gate.next_goal_decision
            gate_next_step_after_ready = $gate.next_step_after_ready
            gate_replay_allowed = $gate.replay_allowed
            strategy_accepted = $false
            live_orders = $false
            selected_branch = "cross_sectional_momentum_daily"
            daily_momentum_candidate_gate = $true
            daily_momentum_report_path = $reportPath
            daily_momentum_validation_path = $validationPath
            daily_momentum_survivorship_audit_path = $survivorshipAuditPath
            daily_momentum_audit_revise_gate = $auditRevise
            channel_intake = "blocked"
        }
        commands = [ordered]@{
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
            daily_momentum_report = $reportPath
            daily_momentum_validation = $validationPath
            daily_momentum_survivorship_audit = if ($survivorshipAuditPath) { $survivorshipAuditPath } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $dailyMomentumSurvivorshipAuditScript -UpdateGate -Json" }
            trading_test_runner_plan = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript -PlanOnly -Json"
            strategy_acceptance_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File $acceptanceGateScript -Json"
        }
        fast_path = [ordered]@{
            reason = "active_gate_daily_momentum_candidate_requires_bias_review"
            skipped_scripts = @(
                $preflightScript,
                $acceptanceGateScript,
                $goalStatusScript,
                $sweepReversalGateScript,
                $swarmStatusScript
            )
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 8
        exit 0
    }

    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Decision: $decision"
    Write-Host "Reason: $reason"
    Write-Host "Primary command:"
    Write-Host "  $($result.primary_command)"
    exit 0
}

$pitUniversePreflightReadyGate = (
    ([string]$gate.next_goal_decision -eq "PIT_UNIVERSE_SNAPSHOT_PREFLIGHT_PLANONLY_READY_FOR_PUBLIC_PROBE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gate.strategy_branch_status.verdict -in @(
            "pit_snapshot_preflight_ready_for_public_probe",
            "pit_public_probe_plan_ready"
        )
    )
)
$pitUniversePublicProbeAcceptedGate = (
    ([string]$gate.next_goal_decision -eq "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gate.strategy_branch_status.verdict -eq "pit_public_probe_accepted_ready_for_visible_snapshot_collect_approval"
    )
)
$pitUniverseCollectApprovalPacketReadyGate = (
    ([string]$gate.next_goal_decision -eq "PIT_UNIVERSE_SNAPSHOT_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION") -or
    ([string]$gate.next_goal_decision -eq "START_NEW_VISIBLE_PIT_UNIVERSE_SNAPSHOT_COLLECT_AFTER_FIX_APPROVAL") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gate.strategy_branch_status.verdict -in @(
            "snapshot_collect_approval_packet_ready_awaiting_explicit_confirmation",
            "control_plane_fixed_ready_for_new_clean_collect_approval"
        )
    )
)
$pitUniversePublicProbeRejectedGate = (
    ([string]$gate.next_goal_decision -eq "PIT_UNIVERSE_PUBLIC_PROBE_REJECTED_RESCOPE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gate.strategy_branch_status.verdict -eq "pit_public_probe_rejected"
    )
)

if ($pitUniversePreflightReadyGate -or $pitUniversePublicProbeAcceptedGate -or $pitUniverseCollectApprovalPacketReadyGate -or $pitUniversePublicProbeRejectedGate) {
    $requiresApproval = $false
    if ($pitUniversePreflightReadyGate) {
        $decision = "PIT_UNIVERSE_PUBLIC_PROBE_READY"
        $reason = "PIT universe snapshot preflight passed. Next step is a short public REST probe of MEXC/Gate contract and ticker fields. No long collect/replay/grid/live/API-key/paper-forward."
        $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniversePublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json"
        $allowedActions = @(
            "run_short_pit_universe_public_probe",
            "verify_contract_status_volume_schema",
            "block_long_collect_replay_grid_live_api_and_paper_forward"
        )
        $nextRequired = "run_short_pit_universe_public_probe"
    } elseif ($pitUniversePublicProbeAcceptedGate) {
        $decision = "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_BUILD_COLLECT_APPROVAL_PACKET_PLANONLY"
        $reason = "PIT universe public probe accepted contract/status/volume schema. Next step is a visible snapshot collector approval packet; actual collect still requires explicit user confirmation."
        $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseCollectApprovalPacketScript -UpdateGate -Json"
        $allowedActions = @(
            "build_visible_pit_snapshot_collect_approval_packet",
            "define_snapshot_cadence_storage_resume_and_monitor",
            "block_actual_collect_until_explicit_confirmation",
            "block_replay_grid_live_api_and_paper_forward"
        )
        $nextRequired = "build_visible_pit_snapshot_collect_approval_packet"
    } elseif ($pitUniverseCollectApprovalPacketReadyGate) {
        $decision = "PIT_UNIVERSE_SNAPSHOT_COLLECT_AWAITING_EXPLICIT_CONFIRMATION"
        $reason = "PIT universe snapshot collect approval packet is ready. Actual collect is a long visible run and requires explicit confirmation; replay/grid/live/API-key/paper-forward remain blocked."
        $primaryCommand = "await explicit confirmation, then run command_after_explicit_approval in a visible terminal"
        $requiresApproval = $true
        $allowedActions = @(
            "await_explicit_confirmation_for_visible_pit_snapshot_collect",
            "show_command_after_explicit_approval",
            "block_replay_grid_live_api_and_paper_forward"
        )
        $nextRequired = "await_explicit_confirmation_for_visible_snapshot_collect"
    } else {
        $decision = "PIT_UNIVERSE_PUBLIC_PROBE_REJECTED_RESCOPE"
        $reason = "PIT universe public probe failed endpoint/schema requirements. Do not collect/replay/grid/live/API-key/paper-forward; rescope or reject this branch."
        $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $structuralBranchPlanOnlyScript -UpdateGate -Json"
        $allowedActions = @(
            "accept_pit_universe_public_probe_rejection",
            "run_structural_branch_planonly",
            "select_or_design_next_research_branch",
            "block_collect_replay_grid_live_api_and_paper_forward"
        )
        $nextRequired = "rescope_or_reject_branch"
    }
    $commandAfterExplicitApproval = if ($rawGate) { $rawGate.command_after_explicit_approval } else { $null }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = $decision
        reason = $reason
        requires_user_approval = $requiresApproval
        requires_user_approval_for_actual_collect = $true
        primary_command = $primaryCommand
        command_after_explicit_approval = $commandAfterExplicitApproval
        allowed_actions = $allowedActions
        blocked_actions = @(
            "long_collect_without_explicit_confirmation",
            "hidden_background_collect",
            "replay",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward"
        )
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            gate_next_goal_decision = $gate.next_goal_decision
            gate_next_step_after_ready = $gate.next_step_after_ready
            gate_replay_allowed = $gate.replay_allowed
            selected_branch = "forward_pit_universe_event_liquidity_anomaly"
            strategy_accepted = $false
            live_orders = $false
            next_step_required = $nextRequired
            last_pit_universe_snapshot_preflight_output_path = if ($rawGate) { $rawGate.last_pit_universe_snapshot_preflight_output_path } else { $null }
            last_pit_universe_public_probe_output_path = if ($rawGate) { $rawGate.last_pit_universe_public_probe_output_path } else { $null }
            last_pit_universe_snapshot_collect_approval_packet_output_path = if ($rawGate) { $rawGate.last_pit_universe_snapshot_collect_approval_packet_output_path } else { $null }
            channel_intake = "blocked"
        }
        commands = [ordered]@{
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
            pit_universe_snapshot_preflight = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseSnapshotPreflightScript -UpdateGate -Json"
            pit_universe_public_probe = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniversePublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json"
            pit_universe_snapshot_collect_approval_packet = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseCollectApprovalPacketScript -UpdateGate -Json"
            pit_universe_visible_collect = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseVisibleCollectScript -PlanOnly -Json"
            next_goal_step = "pwsh -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Json"
        }
        fast_path = [ordered]@{
            reason = "active_gate_pit_universe_path"
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 8
        exit 0
    }

    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Decision: $decision"
    Write-Host "Reason: $reason"
    Write-Host "Primary command:"
    Write-Host "  $primaryCommand"
    exit 0
}

$newStructuralHypothesisGate = (
    ([string]$gate.next_goal_decision -eq "STRUCTURAL_BRANCH_BACKLOG_EXHAUSTED_REQUIRES_NEW_HYPOTHESIS_PLANONLY") -or
    ([string]$gate.next_goal_decision -eq "NEW_STRUCTURAL_HYPOTHESIS_PLANONLY_SELECTED") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.verdict -eq "backlog_exhausted_requires_new_hypothesis_design"
    ) -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly"
    )
)

if ($newStructuralHypothesisGate) {
    $selectedAlready = ([string]$gate.next_goal_decision -eq "NEW_STRUCTURAL_HYPOTHESIS_PLANONLY_SELECTED") -or (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly"
    )
    $decision = if ($selectedAlready) { "FORWARD_PIT_UNIVERSE_EVENT_LIQUIDITY_ANOMALY_PLANONLY_SELECTED" } else { "NEW_STRUCTURAL_HYPOTHESIS_PLANONLY_REQUIRED" }
    $primaryCommand = if ($selectedAlready) { "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseSnapshotPreflightScript -UpdateGate -Json" } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $newStructuralHypothesisPlanOnlyScript -UpdateGate -Json" }
    $reason = if ($selectedAlready) { "A new data-first structural branch is selected. Next step is a point-in-time universe snapshot preflight PlanOnly so future evidence is not current-top-volume survivorship biased." } else { "The existing structural backlog is exhausted on current evidence. Next step is a new hypothesis design packet, not another replay/grid/collect on rejected branches." }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_next_goal_step"
        decision = $decision
        reason = $reason
        requires_user_approval = $false
        requires_user_approval_for_actual_collect = $false
        primary_command = $primaryCommand
        allowed_actions = @(
            "run_new_structural_hypothesis_planonly",
            "build_point_in_time_universe_snapshot_preflight_planonly",
            "define_bias_controlled_data_requirements",
            "block_collect_grid_replay_live_api_and_paper_forward"
        )
        blocked_actions = @(
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "grid_search",
            "hidden_background_collect",
            "reselect_rejected_branch_without_new_data"
        )
        state = [ordered]@{
            gate_status = $gate.status
            gate_run_id = $gate.run_id
            gate_next_goal_decision = $gate.next_goal_decision
            gate_replay_allowed = $gate.replay_allowed
            selected_branch = if ($selectedAlready) { "forward_pit_universe_event_liquidity_anomaly" } else { $null }
            strategy_accepted = $false
            live_orders = $false
            channel_intake = "blocked"
        }
        commands = [ordered]@{
            gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
            new_structural_hypothesis_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File $newStructuralHypothesisPlanOnlyScript -UpdateGate -Json"
            pit_universe_snapshot_preflight = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseSnapshotPreflightScript -UpdateGate -Json"
            pit_universe_public_probe = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniversePublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json"
            next_goal_step = "pwsh -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Json"
        }
        fast_path = [ordered]@{
            reason = "active_gate_new_structural_hypothesis_path"
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 8
        exit 0
    }

    Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Decision: $decision"
    Write-Host "Reason: $reason"
    Write-Host "Primary command:"
    Write-Host "  $primaryCommand"
    exit 0
}

$preflight = Invoke-JsonScript -Path $preflightScript
$acceptance = Invoke-JsonScript -Path $acceptanceGateScript
$goalStatus = Invoke-JsonScript -Path $goalStatusScript
$sweepReversalGate = Invoke-JsonScript -Path $sweepReversalGateScript
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
            [string]$gate.strategy_branch_status.verdict -in @("rejected_base_fees", "rejected_full_scan_base_fees", "rejected_no_net_edge_after_base_fees")
        )
    )
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
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_FIXED_V0*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_EVENT_CENSUS*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_FIXED_V1*") -or
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
$slowLiquidityV0RejectedReadyForCensusGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_V0_REJECTED_NO_EVENT_BASE_RATE_READY_FOR_EVENT_CENSUS_V1_PLANONLY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "fixed_v0_rejected_no_event_base_rate_ready_for_event_census_v1"
    )
)
$slowLiquidityEventCensusAcceptedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_READY_FOR_FIXED_V1_PLANONLY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "event_census_v1_accepted_ready_for_fixed_v1_planonly"
    )
)
$slowLiquidityEventCensusRejectedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_EVENT_CENSUS_V1_REJECTED_INSUFFICIENT_EVENT_BASE_RATE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "event_census_v1_rejected_insufficient_event_base_rate"
    )
)
$slowLiquidityFixedV1ReadyGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_V1_PLANONLY_READY_FOR_REPLAY_VALIDATION") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "fixed_v1_planonly_ready_for_replay_validation"
    )
)
$slowLiquidityReplayV1CandidateGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "fixed_v1_replay_candidate_requires_independent_review"
    )
)
$slowLiquidityReplayV1RejectedGate = (
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gate.strategy_branch_status.verdict -eq "fixed_v1_replay_rejected_no_robust_edge"
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

$visibleFundingCollectCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleCollectScript -Days 7 -ConfirmedLongRun"
$visibleFundingCollectPreviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleCollectScript -Days 7 -PlanOnly"
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
$spotPerpBasisPublicProbeConfirmedCommand = if ($gate.command_after_explicit_approval) { [string]$gate.command_after_explicit_approval } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json" }
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
$listingEventHistoryCollectPreviewPlanOnlyCommand = "manual PlanOnly implementation: build visible listing-event OHLCV history collect preview; do not start actual collect/grid/replay/live/API"
$listingEventReplayPlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventReplayPlanOnlyScript -Json"
$listingEventReplayValidationPacketCommand = "manual PlanOnly implementation: build independent listing-event validation packet; no grid/live/API/paper-forward"
$listingEventActivePlanOnlyCommand = if ($listingEventHistoryAvailabilityReadyGate) { $listingEventHistoryAvailabilityPublicProbeCommand } elseif ($listingEventHistoryAvailabilityAcceptedGate) { $listingEventHistoryCollectApprovalPacketCommand } elseif ($listingEventHistoryAvailabilityRejectedGate) { $listingEventHistoryCollectPreviewCommand } elseif ($listingEventNormalizerReadyGate) { $listingEventNormalizerPlanOnlyCommand } elseif ($listingEventHistoryDataQualityPendingGate) { $listingEventHistoryDataQualityCommand } elseif ($listingEventHistoryDataQualityRejectedGate) { $listingEventHistoryAvailabilityPreflightUpdateGateCommand } elseif ($listingEventHistoryPlanReadyGate) { $listingEventHistoryCollectPreviewCommand } else { $listingEventPlanOnlyCommand }
$listingEventActiveAfterApprovalCommand = if ($listingEventHistoryCollectPreviewAwaitingApprovalGate) { $listingEventHistoryCollectVisibleCommand } else { $listingEventActivePlanOnlyCommand }
$slowLiquidityHistoryPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityHistoryDataPlanScript -Json"
$slowLiquidityHistoryPlanUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityHistoryDataPlanScript -UpdateGate -Json"
$slowLiquidityHistoryAwaitApprovalCommand = "await explicit user approval: подтверждаю visible slow-liquidity OHLCV history collect"
$slowLiquidityFixedSignalPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedSignalPlanScript -Json"
$slowLiquidityFixedSignalPlanUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedSignalPlanScript -UpdateGate -Json"
$slowLiquidityFeatureNormalizerCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFeatureNormalizerScript -Json"
$slowLiquidityFeatureNormalizerUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFeatureNormalizerScript -UpdateGate -Json"
$slowLiquidityRescopePlanOnlyCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityRescopePlanOnlyScript -Json"
$slowLiquidityRescopePlanOnlyUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityRescopePlanOnlyScript -UpdateGate -Json"
$slowLiquidityEventCensusCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityEventCensusScript -Json"
$slowLiquidityEventCensusUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityEventCensusScript -UpdateGate -Json"
$slowLiquidityFixedV1PlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedV1PlanScript -Json"
$slowLiquidityFixedV1PlanUpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedV1PlanScript -UpdateGate -Json"
$slowLiquidityReplayV1Command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityReplayV1Script -Json"
$slowLiquidityReplayV1UpdateGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityReplayV1Script -UpdateGate -Json"
$slowLiquidityFixedReplayValidationCommand = "manual PlanOnly implementation: run fixed slow-liquidity replay-validation from feature normalizer artifact; no grid/live/API/paper-forward"
$slowLiquidityFixedV1ReplayValidationCommand = $slowLiquidityReplayV1UpdateGateCommand
$slowLiquidityIndependentReviewCommand = "manual independent review: send fixed slow-liquidity v1 replay artifact to Rой/reviewer; no paper-forward/live/API/grid"
$slowLiquidityRejectedSelectNextBranchCommand = $structuralBranchPlanOnlyCommand
$slowLiquidityActivePlanOnlyCommand = if ($slowLiquidityReplayV1CandidateGate) { $slowLiquidityIndependentReviewCommand } elseif ($slowLiquidityReplayV1RejectedGate) { $slowLiquidityRejectedSelectNextBranchCommand } elseif ($slowLiquidityFixedV1ReadyGate) { $slowLiquidityFixedV1ReplayValidationCommand } elseif ($slowLiquidityEventCensusAcceptedGate) { $slowLiquidityFixedV1PlanUpdateGateCommand } elseif ($slowLiquidityEventCensusRejectedGate) { $slowLiquidityRejectedSelectNextBranchCommand } elseif ($slowLiquidityV0RejectedReadyForCensusGate) { $slowLiquidityEventCensusUpdateGateCommand } elseif ($slowLiquidityFeatureNormalizerReadyGate) { $slowLiquidityFixedReplayValidationCommand } elseif ($slowLiquidityFeatureNormalizerRejectedGate) { $slowLiquidityRescopePlanOnlyUpdateGateCommand } elseif ($slowLiquidityFixedSignalReadyGate) { $slowLiquidityFeatureNormalizerUpdateGateCommand } elseif ($slowLiquidityHistoryQualityAcceptedGate) { $slowLiquidityFixedSignalPlanUpdateGateCommand } elseif ($slowLiquidityHistoryDataPlanReadyGate) { $slowLiquidityHistoryAwaitApprovalCommand } elseif ($slowLiquidityDataAvailabilityReadyGate) { $slowLiquidityDataAvailabilityPreflightUpdateGateCommand } elseif ($slowLiquidityDataAvailabilityRejectedGate) { $slowLiquidityHistoryPlanUpdateGateCommand } elseif ($slowLiquidityDataAvailabilityAcceptedGate) { $slowLiquidityFixedSignalPlanUpdateGateCommand } else { $slowLiquidityPlanOnlyCommand }
$slowLiquidityExactRecollectPreflightCommand = if ($slowLiquidityExactRecollectAwaitingApprovalGate) { [string]$slowLiquidityExactRecollectStatus.preflight_command } else { "blocked: repair exact slow-liquidity recollect PlanOnly/readiness binding" }
$slowLiquidityExactRecollectApprovalPacketCommand = if ($slowLiquidityExactRecollectAwaitingApprovalGate) { [string]$slowLiquidityExactRecollectStatus.approval_packet_command } else { "blocked: exact slow-liquidity approval packet is not the current lifecycle action" }
$visibleWsCollectCommandResolution = Resolve-WsCollectCommands -ScriptPath $visibleWsCollectScript -PlanPreviewPath $visibleWsPlanPreviewLatest
$visibleWsCollectPreviewCommand = $visibleWsCollectCommandResolution.preview_command
$visibleWsCollectCommand = $visibleWsCollectCommandResolution.command
$visibleCollectPreviewCommand = if ($slowLiquidityExactRecollectAwaitingApprovalGate -or $slowLiquidityExactRecollectIntegrityBlockedGate) { $slowLiquidityExactRecollectPreflightCommand } elseif ($slowLiquiditySelectedGate) { $slowLiquidityActivePlanOnlyCommand } elseif ($spotPerpBasisAvailabilityRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($spotPerpBasisSelectedGate) { $spotPerpBasisActivePlanOnlyCommand } elseif ($listingEventReplayRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($listingEventReplayCandidateGate) { $listingEventReplayValidationPacketCommand } elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) { $listingEventActivePlanOnlyCommand } elseif ($crossVenueStructuralSelectedGate) { $crossVenueImplementationPlanOnlyCommand } elseif ($fundingRejectedBaseFeesGate) { $structuralBranchPlanOnlyCommand } elseif ($liquiditySweepRejectedGate) { $fundingBasisPlanOnlyCommand } elseif ($fundingBlockedBySwarm) { $visibleWsCollectPreviewCommand } else { $visibleFundingCollectPreviewCommand }
$visibleCollectCommand = if ($slowLiquidityExactRecollectAwaitingApprovalGate -or $slowLiquidityExactRecollectIntegrityBlockedGate) { $slowLiquidityExactRecollectPreflightCommand } elseif ($slowLiquiditySelectedGate) { $slowLiquidityActivePlanOnlyCommand } elseif ($spotPerpBasisAvailabilityRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($spotPerpBasisSelectedGate) { $spotPerpBasisActivePlanOnlyCommand } elseif ($listingEventReplayRejectedGate) { $structuralBranchPlanOnlyCommand } elseif ($listingEventReplayCandidateGate) { $listingEventReplayValidationPacketCommand } elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) { $listingEventActiveAfterApprovalCommand } elseif ($crossVenueStructuralSelectedGate) { $crossVenueImplementationPlanOnlyCommand } elseif ($fundingRejectedBaseFeesGate) { $structuralBranchPlanOnlyCommand } elseif ($liquiditySweepRejectedGate) { $fundingBasisPlanOnlyCommand } elseif ($fundingBlockedBySwarm) { $visibleWsCollectCommand } else { $visibleFundingCollectCommand }
$visibleCollectPreviewShortcut = if ($slowLiquiditySelectedGate -or $spotPerpBasisAvailabilityRejectedGate -or $spotPerpBasisSelectedGate -or $listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate -or $crossVenueStructuralSelectedGate -or $fundingRejectedBaseFeesGate -or $liquiditySweepRejectedGate) { "" } elseif ($fundingBlockedBySwarm) { $previewDenseWsShortcut } else { $preview7dFundingShortcut }
$visibleCollectConfirmedShortcut = if ($slowLiquiditySelectedGate -or $spotPerpBasisAvailabilityRejectedGate -or $spotPerpBasisSelectedGate -or $listingEventReplayRejectedGate -or $listingEventReplayCandidateGate -or $crossVenueRejectedGate -or $listingEventSelectedGate -or $crossVenueStructuralSelectedGate -or $fundingRejectedBaseFeesGate -or $liquiditySweepRejectedGate) { "" } elseif ($fundingBlockedBySwarm) { $startDenseWsShortcut } else { $start7dFundingShortcut }
$visibleCollectLegacyResolution = if ($slowLiquidityExactRecollectIntegrityBlockedGate) {
    "slow_liquidity_exact_recollect_integrity_blocked"
} elseif ($slowLiquidityExactRecollectAwaitingApprovalGate) {
    "slow_liquidity_exact_recollect_awaiting_exact_hash_bound_approval"
} elseif ($slowLiquiditySelectedGate) {
    "slow_liquidity_regime_breakout_retest_planonly_selected_no_collect"
} elseif ($spotPerpBasisAvailabilityRejectedGate) {
    "spot_perp_basis_public_probe_rejected_select_next_non_hft_branch"
} elseif ($crossVenueStructuralSelectedGate) {
    "cross_venue_dislocation_planonly_selected_no_collect"
} elseif ($spotPerpBasisSelectedGate) {
    "spot_perp_basis_mean_reversion_planonly_selected_no_collect"
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
$finalReviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $finalReviewScript"
$preflightCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $preflightScript"
$acceptanceCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $acceptanceGateScript"
$fundingGapCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingViabilityGapScript"
$fundingCostGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingCostAssumptionGateScript"
$fundingCandidateWatchlistCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingCandidateWatchlistScript"
$fundingWatchlistReviewCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingWatchlistReviewScript"
$sweepReversalGateCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $sweepReversalGateScript"

$decision = "UNKNOWN"
$allowedActions = @()
$blockedActions = @(
    "new_channel_analysis",
    "stale_internal_goal_channel_resume",
    "hidden_background_long_runs",
    "live_orders",
    "api_keys",
    "leverage_or_margin",
    "paper_forward_without_accepted_research",
    "winrate_claim_without_expectancy_net_pnl_oos_walk_stress"
)
$requiresUserApproval = $false
$requiresUserApprovalForActualCollect = $false
$primaryCommand = ""
$reason = ""

if ([string]$gate.status -eq "RUNNING") {
    $decision = "STATUS_ONLY"
    $allowedActions = @("status_eta_checks_only")
    $primaryCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
    $reason = "Active run gate is RUNNING. Do not postprocess, grid, code-edit for the goal, analyze broadly, or start new runs."
} elseif ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
    $decision = "RESUME_OR_REJECT_INCOMPLETE_DATASET"
    $allowedActions = @("visible_resume_current_run", "explicitly_mark_dataset_incomplete")
    $requiresUserApproval = $true
    $requiresUserApprovalForActualCollect = $true
    $primaryCommand = "inspect active-run gate, then visibly resume the incomplete run or explicitly reject the dataset"
    $reason = "Active run gate is STOPPED_INCOMPLETE. The next proof step cannot treat the dataset as ready."
} elseif (-not [bool]$preflight.ok) {
    $decision = "FIX_PREFLIGHT"
    $allowedActions = @("fix_failed_preflight_checks")
    $primaryCommand = $preflightCommand
    $reason = "Edge preflight is not clean. Fix failed checks before continuing."
} elseif ([string]$acceptance.stage -eq "paper_forward_validated_live_still_blocked") {
    $decision = "LIVE_READINESS_REVIEW_REQUIRED"
    $allowedActions = @("run_live_readiness_review", "complete_venue_risk_cards", "verify_api_key_controls")
    $requiresUserApproval = $true
    $requiresUserApprovalForActualCollect = $true
    $primaryCommand = "manual live-readiness review required; no live command is provided"
    $reason = "Paper-forward is validated, but live remains blocked until separate live-readiness review and explicit approval."
} elseif ([string]$acceptance.stage -eq "research_accepted_paper_forward_required") {
    $decision = "PAPER_FORWARD_REQUIRED"
    $allowedActions = @("freeze_config", "prepare_visible_paper_forward", "run_paper_forward_only_after_plan_review")
    $requiresUserApproval = $true
    $requiresUserApprovalForActualCollect = $true
    $primaryCommand = "prepare paper-forward plan; live remains blocked"
    $reason = "Research accepted but paper-forward has not been accepted. Live is still blocked."
} elseif ([string]$acceptance.stage -eq "research_only_no_accepted_strategy") {
    if ($slowLiquidityExactRecollectIntegrityBlockedGate) {
        $decision = "SLOW_LIQUIDITY_EXACT_RECOLLECT_INTEGRITY_BLOCKED"
        $allowedActions = @(
            "inspect_exact_slow_liquidity_recollect_binding",
            "repair_immutable_planonly_readiness_binding"
        )
        $blockedActions += @(
            "collector_before_exact_approval",
            "approval_receipt_creation_with_mismatched_hashes",
            "launch_record_or_output_creation"
        )
        $primaryCommand = $slowLiquidityExactRecollectPreflightCommand
        $reason = "The exact slow-liquidity recollect PlanOnly/readiness binding failed closed. Repair and refreeze it before requesting approval or starting any collector."
    } elseif ($slowLiquidityExactRecollectAwaitingApprovalGate) {
        $decision = "SLOW_LIQUIDITY_EXACT_RECOLLECT_AWAITING_EXACT_APPROVAL"
        $allowedActions = @(
            "await_exact_hash_bound_slow_liquidity_recollect_approval",
            "read_current_exact_approval_packet",
            "run_non_starting_approval_freeze_preflight",
            "quick_status_checks"
        )
        $blockedActions += @(
            "collector_before_exact_approval",
            "approval_receipt_before_matching_user_text",
            "launch_record_or_output_before_exact_approval"
        )
        $requiresUserApproval = $true
        $requiresUserApprovalForActualCollect = $true
        $primaryCommand = $slowLiquidityExactRecollectApprovalPacketCommand
        $reason = "The page-cap-fix recollect PlanOnly is frozen and internally consistent. Read the current exact approval packet with the non-writing approval-freeze preflight, then await matching exact user text."
    } elseif ($slowLiquiditySelectedGate) {
        $decision = if ($slowLiquidityReplayV1CandidateGate) {
            "SLOW_LIQUIDITY_FIXED_V1_REPLAY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW"
        } elseif ($slowLiquidityReplayV1RejectedGate) {
            "SLOW_LIQUIDITY_FIXED_V1_REPLAY_REJECTED_SELECT_NEXT_BRANCH"
        } elseif ($slowLiquidityFixedV1ReadyGate) {
            "SLOW_LIQUIDITY_FIXED_V1_READY_FOR_REPLAY_VALIDATION"
        } elseif ($slowLiquidityEventCensusAcceptedGate) {
            "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_BUILD_FIXED_V1_PLANONLY"
        } elseif ($slowLiquidityEventCensusRejectedGate) {
            "SLOW_LIQUIDITY_EVENT_CENSUS_V1_REJECTED_SELECT_NEXT_BRANCH"
        } elseif ($slowLiquidityV0RejectedReadyForCensusGate) {
            "SLOW_LIQUIDITY_FIXED_V0_REJECTED_RUN_EVENT_CENSUS_V1_PLANONLY"
        } elseif ($slowLiquidityFeatureNormalizerReadyGate) {
            "SLOW_LIQUIDITY_FEATURE_NORMALIZER_READY_FOR_FIXED_REPLAY_VALIDATION"
        } elseif ($slowLiquidityFeatureNormalizerRejectedGate) {
            "SLOW_LIQUIDITY_FEATURE_NORMALIZER_REJECTED_RESCOPE_V0_PLANONLY"
        } elseif ($slowLiquidityFixedSignalReadyGate) {
            "SLOW_LIQUIDITY_FIXED_SIGNAL_READY_BUILD_FEATURE_NORMALIZER"
        } elseif ($slowLiquidityHistoryQualityAcceptedGate) {
            "SLOW_LIQUIDITY_HISTORY_QUALITY_ACCEPTED_DEFINE_FIXED_SIGNAL"
        } elseif ($slowLiquidityHistoryDataPlanReadyGate) {
            "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_AWAITING_EXPLICIT_APPROVAL"
        } elseif ($slowLiquidityDataAvailabilityRejectedGate) {
            "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_BUILD_HISTORY_PLAN"
        } elseif ($slowLiquidityDataAvailabilityAcceptedGate) {
            "SLOW_LIQUIDITY_DATA_AVAILABILITY_ACCEPTED_DEFINE_FIXED_SIGNAL"
        } else {
            "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT"
        }
        $allowedActions = @(
            "run_slow_liquidity_regime_breakout_retest_planonly",
            "run_slow_liquidity_data_availability_preflight_planonly",
            "run_slow_liquidity_fixed_signal_planonly",
            "run_slow_liquidity_feature_normalizer_planonly",
            "run_slow_liquidity_rescope_planonly",
            "run_slow_liquidity_event_census_v1_planonly",
            "run_slow_liquidity_fixed_v1_planonly",
            "run_fixed_slow_liquidity_replay_validation_planonly_when_normalizer_allows",
            "run_fixed_slow_liquidity_v1_replay_validation_planonly_when_contract_allows",
            "independent_review_before_paper_forward",
            "build_slow_liquidity_feature_normalizer_planonly",
            "build_slow_liquidity_data_availability_preflight_planonly",
            "build_slow_liquidity_history_data_plan_approval_packet_planonly",
            "await_explicit_user_approval_for_slow_liquidity_history_collect",
            "define_fixed_v0_regime_signal_before_replay",
            "block_collect_grid_replay_live_api_and_paper_forward",
            "retry_swarm_at_next_major_branch_decision",
            "continue_manual_codex_when_swarm_limited"
        )
        $requiresUserApproval = [bool]$slowLiquidityHistoryDataPlanReadyGate
        $requiresUserApprovalForActualCollect = [bool]$slowLiquidityHistoryDataPlanReadyGate
        $primaryCommand = $slowLiquidityActivePlanOnlyCommand
        $reason = if ($slowLiquidityReplayV1CandidateGate) {
            "slow_liquidity fixed v1 replay is a candidate, not an accepted strategy. Next valid work is independent review; no paper-forward/live/API/grid."
        } elseif ($slowLiquidityReplayV1RejectedGate) {
            "slow_liquidity fixed v1 replay was rejected by robustness/economics gates. Select another structural PlanOnly branch; do not tune parameters after replay."
        } elseif ($slowLiquidityFixedV1ReadyGate) {
            "slow_liquidity fixed v1 signal contract is ready. Next valid work is one fixed-parameter replay-validation PlanOnly; no grid/live/API/paper-forward."
        } elseif ($slowLiquidityEventCensusAcceptedGate) {
            "slow_liquidity_regime_breakout_retest event-census v1 found enough event base-rate. Next valid work is fixed v1 signal PlanOnly; no replay/grid/live/API/paper-forward until the fixed v1 contract exists."
        } elseif ($slowLiquidityEventCensusRejectedGate) {
            "slow_liquidity_regime_breakout_retest event-census v1 did not find enough event base-rate. Reject this slow-liquidity branch on current evidence and select another structural PlanOnly branch; do not collect larger history under v0."
        } elseif ($slowLiquidityV0RejectedReadyForCensusGate) {
            "slow_liquidity fixed v0 is rejected for no event base-rate. Next valid work is event-census v1 PlanOnly on existing 56d 1h/4h history; no replay/grid/live/API/paper-forward and no larger v0 collect."
        } elseif ($slowLiquidityFeatureNormalizerReadyGate) {
            "slow_liquidity_regime_breakout_retest feature normalizer is ready. Next valid work is one fixed-parameter replay-validation PlanOnly from the normalizer artifact; no grid, live orders, API keys, leverage, margin or paper-forward."
        } elseif ($slowLiquidityFeatureNormalizerRejectedGate) {
            "slow_liquidity_regime_breakout_retest feature normalizer rejected the fixed v0 event set as insufficient. Next valid work is formal v0 rescope PlanOnly; do not replay/grid or collect larger history under v0."
        } elseif ($slowLiquidityFixedSignalReadyGate) {
            "slow_liquidity_regime_breakout_retest fixed v0 signal PlanOnly is ready. Next valid work is feature normalizer PlanOnly on clean 1h/4h two-venue slice; no grid, live orders, API keys, leverage, margin or paper-forward, and replay only after normalizer artifact exists."
        } elseif ($slowLiquidityHistoryQualityAcceptedGate) {
            "slow_liquidity_regime_breakout_retest history data-quality accepted. Next valid work is fixed v0 signal contract PlanOnly before any replay; no grid, live orders, API keys, leverage, margin or paper-forward."
        } elseif ($slowLiquidityHistoryDataPlanReadyGate) {
            "slow_liquidity_regime_breakout_retest history data plan is ready. Await explicit approval before implementing/running a visible OHLCV history collector; no replay, grid, live orders, API keys, leverage, margin or paper-forward."
        } elseif ($slowLiquidityDataAvailabilityRejectedGate) {
            "slow_liquidity_regime_breakout_retest data availability preflight rejected current local data: multi-week 15m/1h/4h history and event sample are not sufficient. Next valid work is a history data plan/approval packet only; no collect, grid, replay, live orders, API keys, leverage, margin or paper-forward."
        } elseif ($slowLiquidityDataAvailabilityAcceptedGate) {
            "slow_liquidity_regime_breakout_retest data availability preflight accepted enough raw coverage. Next valid work is fixed v0 signal contract PlanOnly before any replay; no grid, live orders, API keys, leverage, margin or paper-forward."
        } else {
            "slow_liquidity_regime_breakout_retest is selected after spot/perp public-probe rejection. Next valid work is read-only PlanOnly data availability preflight; no collect, grid, replay, live orders, API keys, leverage, margin or paper-forward."
        }
    } elseif ($spotPerpBasisAvailabilityRejectedGate) {
        $decision = if ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") { "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE" } else { "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_RESCOPE" }
        $allowedActions = @(
            "accept_spot_perp_basis_rejection_on_current_public_probe",
            "run_structural_branch_planonly",
            "block_collect_grid_replay_live_api_and_paper_forward"
        )
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $primaryCommand = $structuralBranchPlanOnlyCommand
        $reason = "spot/perp basis availability/public probe rejected the branch under current public-data/coverage constraints. Select a new structural PlanOnly branch; no collect/grid/replay/live/API/paper-forward."
    } elseif ($spotPerpBasisSelectedGate) {
        if ($spotPerpBasisAvailabilityAwaitingProbeGate) {
            $decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION"
            $allowedActions = @(
                "await_explicit_confirmation_for_short_public_spot_perp_availability_probe",
                "prepare_or_read_command_after_explicit_approval",
                "block_collect_grid_replay_live_api_and_paper_forward",
                "keep_funding_as_risk_filter_not_pnl_source"
            )
            $requiresUserApproval = $true
            $requiresUserApprovalForActualCollect = $true
            $primaryCommand = $spotPerpBasisPublicProbePlanCommand
            $reason = "spot/perp basis availability preflight found public endpoints, but existing files are not backtest-ready. Next action requires explicit confirmation for a short visible public REST availability probe."
        } elseif ($spotPerpBasisAvailabilityRejectedGate) {
            $decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_RESCOPE"
            $allowedActions = @(
                "reject_or_rescope_spot_perp_basis_branch",
                "select_next_non_hft_structural_branch_planonly",
                "block_collect_grid_replay_live_api_and_paper_forward"
            )
            $requiresUserApproval = $false
            $requiresUserApprovalForActualCollect = $false
            $primaryCommand = $structuralBranchPlanOnlyCommand
            $reason = "spot/perp basis availability/public probe rejected the branch under current public-data/coverage constraints. Rescope or select a new branch; no collect/grid/replay/live/API/paper-forward."
        } elseif ($spotPerpBasisAvailabilityPreflightReadyGate) {
            $decision = "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT"
            $allowedActions = @(
                "run_spot_perp_basis_availability_preflight_planonly",
                "block_collect_grid_replay_live_api_and_paper_forward",
                "keep_funding_as_risk_filter_not_pnl_source"
            )
            $requiresUserApproval = $false
            $requiresUserApprovalForActualCollect = $false
            $primaryCommand = $spotPerpBasisAvailabilityPreflightUpdateGateCommand
            $reason = "spot_perp_basis_mean_reversion_no_funding scaffold is built. Run paired spot/perp availability preflight PlanOnly; no collect/grid/replay/live/API/paper-forward."
        } else {
            $decision = "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_RESEARCH"
            $allowedActions = @(
                "run_spot_perp_basis_mean_reversion_planonly",
                "define_paired_spot_perp_availability_preflight",
                "block_collect_grid_replay_live_api_and_paper_forward",
                "keep_funding_as_risk_filter_not_pnl_source",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
            $requiresUserApproval = $false
            $requiresUserApprovalForActualCollect = $false
            $primaryCommand = $spotPerpBasisPlanOnlyCommand
            $reason = "spot_perp_basis_mean_reversion_no_funding is the selected non-HFT structural PlanOnly branch after listing_event_drift_reversal rejection. Build the research scaffold and paired spot/perp availability preflight; no collect/grid/replay/live/API/paper-forward."
        }
    } elseif ($listingEventReplayRejectedGate) {
        $decision = "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_SELECT_NEXT_BRANCH"
        $allowedActions = @(
            "accept_listing_event_drift_reversal_rejection_on_current_sample",
            "run_structural_branch_planonly",
            "or_design_larger_independent_listing_event_sample_planonly",
            "do_not_start_collect_grid_replay_live_api_or_paper_forward",
            "retry_swarm_at_next_major_branch_decision",
            "continue_manual_codex_when_swarm_limited"
        )
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $primaryCommand = $structuralBranchPlanOnlyCommand
        $reason = "listing_event_drift_reversal fixed replay PlanOnly is rejected on current evidence: net expectancy/stress/walk-forward did not pass. Next valid step is selecting a new non-HFT structural branch PlanOnly or designing a larger independent listing-event sample; no collect/grid/replay/live/API/paper-forward."
    } elseif ($listingEventReplayCandidateGate) {
        $decision = "LISTING_EVENT_REPLAY_PLANONLY_CANDIDATE_VALIDATE_INDEPENDENTLY"
        $allowedActions = @(
            "build_independent_listing_event_validation_packet",
            "preserve_fixed_config_no_grid",
            "require_new_oos_walk_forward_stress_economics_before_paper_forward",
            "do_not_start_collect_grid_live_api_or_paper_forward",
            "retry_swarm_at_next_major_branch_decision",
            "continue_manual_codex_when_swarm_limited"
        )
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $primaryCommand = $listingEventReplayValidationPacketCommand
        $reason = "listing_event_drift_reversal is only a candidate, not accepted. It requires independent validation before paper-forward; no grid, live orders, API keys, leverage, margin or paper-forward."
    } elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) {
        if ($listingEventHistoryAvailabilityReadyGate) {
            $decision = "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION"
            $allowedActions = @(
                "await_explicit_confirmation_for_public_history_availability_probe",
                "do_not_start_actual_collect_grid_replay_live_api_or_paper_forward",
                "keep_public_probe_visible_and_short",
                "retain_no_data_delisted_outcomes",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventHistoryAvailabilityAcceptedGate) {
            $decision = "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_BUILD_COLLECT_APPROVAL_PACKET"
            $allowedActions = @(
                "build_revised_visible_history_collect_approval_packet",
                "do_not_start_actual_collect_without_explicit_user_confirmation",
                "keep_replay_grid_live_api_and_paper_forward_blocked",
                "retain_no_data_delisted_outcomes",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventHistoryAvailabilityRejectedGate) {
            $decision = "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_RESAMPLE_OR_GATE_FIX_PLANONLY"
            $allowedActions = @(
                "resample_listing_events_for_two_venue_history_coverage",
                "fix_gate_history_endpoint_mapping_if_needed",
                "retain_no_data_delisted_outcomes",
                "do_not_start_collect_grid_replay_live_api_or_paper_forward",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventHistoryDataQualityRejectedGate) {
            $decision = "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN"
            $allowedActions = @(
                "inspect_listing_event_history_data_quality_reasons",
                "run_listing_event_history_availability_preflight_planonly",
                "improve_gateio_historical_coverage_or_resample_two_venue_ok_events",
                "retain_no_data_delisted_outcomes",
                "do_not_start_collect_grid_replay_live_api_or_paper_forward",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventHistoryDataQualityPendingGate) {
            $decision = "LISTING_EVENT_HISTORY_DATA_QUALITY_REQUIRED"
            $allowedActions = @(
                "run_listing_event_history_data_quality_gate",
                "keep_replay_blocked_until_history_quality_passes",
                "do_not_start_grid_replay_live_api_or_paper_forward",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) {
            $decision = "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL"
            $allowedActions = @(
                "await_explicit_user_approval_before_visible_history_collect",
                "do_not_start_collect_grid_replay_live_api_or_paper_forward",
                "keep_replay_blocked_until_history_quality_passes",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventHistoryPlanReadyGate) {
            $decision = "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_PLANONLY_RESEARCH"
            $allowedActions = @(
                "run_listing_event_history_collect_preview_planonly",
                "define_visible_history_collect_contract_without_starting",
                "keep_replay_blocked_until_history_quality_passes",
                "preserve_survivorship_controls",
                "no_actual_collect_grid_replay_live_api_or_paper_forward",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } elseif ($listingEventNormalizerReadyGate) {
            $decision = "LISTING_EVENT_NORMALIZER_PLANONLY_RESEARCH"
            $allowedActions = @(
                "run_listing_event_normalizer_planonly",
                "measure_listing_event_overlap_with_clean_ws_slice",
                "block_replay_if_overlap_is_insufficient",
                "preserve_base_fee_cost_hurdle",
                "no_collect_grid_live_api_or_paper_forward",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        } else {
            $decision = "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_RESEARCH"
            $allowedActions = @(
                "build_listing_event_drift_reversal_planonly_scaffold",
                "define_listing_calendar_and_survivorship_controls",
                "define_base_fee_cost_hurdle",
                "define_oos_walk_forward_stress_economics_gates",
                "no_collect_grid_live_api_or_paper_forward",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
        }
        $requiresUserApproval = [bool]($listingEventHistoryAvailabilityReadyGate -or $listingEventHistoryCollectPreviewAwaitingApprovalGate)
        $requiresUserApprovalForActualCollect = [bool]$listingEventHistoryCollectPreviewAwaitingApprovalGate
        $primaryCommand = if ($listingEventHistoryAvailabilityReadyGate) { $listingEventHistoryAvailabilityPublicProbeCommand } elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) { "await explicit user approval before implementing/running visible public OHLCV history collect" } else { $listingEventActivePlanOnlyCommand }
        $reason = if ($listingEventHistoryAvailabilityReadyGate) { "Listing-event history availability preflight is PlanOnly-ready. Next step is a short visible public REST probe after explicit confirmation; no actual collect, replay, grid, live orders, API keys, leverage, margin or paper-forward." } elseif ($listingEventHistoryAvailabilityAcceptedGate) { "Listing-event history availability probe accepted enough two-venue coverage. Next step is revised collect approval packet; actual visible OHLCV history collect still needs explicit confirmation." } elseif ($listingEventHistoryAvailabilityRejectedGate) { "Listing-event history availability probe rejected current sample or venue mapping. Resample/fix coverage before any actual collect, replay, grid, live orders, API keys, leverage, margin or paper-forward." } elseif ($listingEventHistoryDataQualityRejectedGate) { "Listing-event history data-quality rejected the collected dataset. Current evidence is not replayable; run availability preflight before any repeated collect, replay, grid, live orders, API keys, leverage, margin or paper-forward." } elseif ($listingEventHistoryDataQualityPendingGate) { "Listing-event OHLCV history collect completed. Next valid step is guarded data-quality; no replay, grid, live orders, API keys, leverage, margin or paper-forward." } elseif ($listingEventNormalizerReadyGate) { "Listing calendar/history quality passed controls. Next valid step is read-only listing_event normalizer PlanOnly; no collect, grid, live orders, API keys, leverage, margin or paper-forward." } elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) { "Listing-event OHLCV history collect preview is ready. Await explicit user approval before implementing/running visible public-history collect; no replay, grid, live orders, API keys, leverage, margin or paper-forward." } elseif ($listingEventHistoryPlanReadyGate) { "Listing-event normalizer found insufficient overlap in the current WS slice. Next valid step is listing-event OHLCV history collect preview PlanOnly; no actual collect, grid, replay, live orders, API keys, leverage, margin or paper-forward." } else { "cross_venue_spot_dislocation_inventory_rebalance full scan was rejected under base fees/buffers. Next valid step is listing_event_drift_reversal as PlanOnly research scaffolding only; no collect, grid, live orders, API keys, leverage, margin or paper-forward." }
    } elseif ($crossVenueStructuralSelectedGate) {
        $decision = "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH"
        $allowedActions = @(
            "implement_cross_venue_dislocation_planonly_detector",
            "define_inventory_rebalance_economics",
            "define_oos_walk_forward_stress_economics_gates",
            "use_existing_clean_72h_mexc_gate_data_first",
            "no_collect_grid_live_api_or_paper_forward",
            "retry_swarm_at_next_major_branch_decision",
            "continue_manual_codex_when_swarm_limited"
        )
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $primaryCommand = $crossVenueImplementationPlanOnlyCommand
        $reason = "cross_venue_spot_dislocation_inventory_rebalance is selected as the next non-HFT structural branch. Implement a read-only PlanOnly detector/backtester on existing clean 72h MEXC/Gate data; no collect, grid, live orders, API keys, leverage, margin or paper-forward."
    } elseif ($fundingRejectedBaseFeesGate) {
        $decision = "DESIGN_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY"
        $allowedActions = @(
            "run_structural_branch_planonly",
            "define_data_requirements",
            "define_oos_walk_forward_stress_economics_gates",
            "prepare_non_starting_research_plan",
            "retry_swarm_at_next_major_branch_decision",
            "continue_manual_codex_when_swarm_limited"
        )
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $primaryCommand = $structuralBranchPlanOnlyCommand
        $reason = "Funding/basis carry is rejected under base/VIP0/no-volume fees. The next valid goal step is a new non-HFT structural research branch PlanOnly, not another funding collect or fee-discount review."
    } elseif ($liquiditySweepRejectedGate) {
        $decision = "FUNDING_BASIS_CARRY_STRUCTURAL_PLANONLY"
        $allowedActions = @(
            "run_funding_basis_planonly",
            "read_only_funding_cost_assumption_gate",
            "read_only_funding_viability_gap",
            "read_only_funding_candidate_watchlist",
            "read_only_funding_watchlist_review",
            "collect_non_secret_fee_tier_evidence_if_user_provides_it",
            "design_next_non_hft_structural_branch_if_funding_remains_unaccepted",
            "retry_swarm_at_next_major_branch_decision",
            "continue_manual_codex_when_swarm_limited"
        )
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $primaryCommand = $fundingBasisPlanOnlyCommand
        $swarmNote = if ($swarmLimited) { " Latest swarm checkpoint is swarm_limited; manual Codex fallback remains active until swarm runtime recovers." } else { "" }
        $reason = "liquidity_sweep_reversal was rejected by active validation gate. Next branch is funding/basis carry as PlanOnly diagnostics only; no collect/grid/live/API/paper-forward. Current-cost funding evidence must pass economics/fee-tier gates before any new visible collect is justified.$swarmNote"
    } elseif ($fundingBlockedBySwarm) {
        if ($feeTierEvidencePresent) {
            $decision = "FUNDING_CARRY_BLOCKED_VALIDATE_FEE_EVIDENCE"
            $allowedActions = @(
                "read_only_funding_cost_assumption_gate",
                "validate_account_fee_tiers_if_user_provides_non_secret_values",
                "retry_swarm_if_fee_evidence_changes_branch_decision"
            )
            $requiresUserApproval = $false
            $primaryCommand = $fundingCostGateCommand
            $reason = "7d funding collect is complete and the prior funding-carry branch was blocked by `Рой` L1/L2, but fee-tier evidence exists. Validate whether it materially changes economics before abandoning funding."
        } else {
            $decision = "SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT"
            $allowedActions = @(
                "short_edge_proof_engineering_only_if_it_changes_future_proof_quality",
                "run_sweep_reversal_acceptance_gate",
                "build_visible_ws_collect_plan",
                "prepare_visible_collector_wrapper_before_any_long_run",
                "run_guarded_ws_postprocess_after_collect",
                "run_guarded_ws_replay_validation_after_accepted_postprocess",
                "run_ws_data_quality_gate_after_normalize",
                "request_explicit_user_approval_before_any_visible_long_collect",
                "retry_swarm_at_next_major_branch_decision",
                "continue_manual_codex_when_swarm_limited"
            )
            $requiresUserApproval = $false
            $requiresUserApprovalForActualCollect = $true
            $primaryCommand = $visibleWsCollectPreviewCommand
            $swarmNote = if ($swarmLimited) { " Latest swarm checkpoint is swarm_limited; manual Codex fallback remains active until swarm runtime recovers." } else { "" }
            $reason = "7d funding collect is complete and the prior funding-carry branch was blocked by `Рой` L1/L2. No fee-tier evidence is present. Sweep/reversal tooling now has train/OOS, walk-forward, stress and acceptance gates, and the current old dataset is rejected. Next useful step is only a visible dense-data collection plan; no long collect without explicit approval.$swarmNote"
        }
    } else {
        $decision = "AWAIT_USER_APPROVAL_FOR_VISIBLE_7D_COLLECT"
        $allowedActions = @(
            "short_edge_proof_engineering",
            "read_only_funding_viability_gap_diagnostic",
            "read_only_funding_cost_assumption_gate",
            "read_only_funding_candidate_watchlist",
            "read_only_funding_watchlist_review",
            "visible_7d_funding_collect_only_after_explicit_user_approval",
            "do_nothing_until_user_approval_if_no_short_engineering_needed"
        )
        $requiresUserApproval = $true
        $requiresUserApprovalForActualCollect = $true
        $primaryCommand = $visibleCollectCommand
        $reason = "No accepted strategy exists. Current 24h funding branch is rejected economically; the next proof step is longer visible funding/basis data collection, but only after explicit user approval."
    }
} else {
    $decision = "MANUAL_REVIEW_REQUIRED"
    $allowedActions = @("inspect_preflight_acceptance_goal_status")
    $primaryCommand = "$preflightCommand ; $acceptanceCommand"
    $reason = "Unexpected acceptance stage. Inspect status before doing goal work."
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_next_goal_step"
    decision = $decision
    reason = $reason
    requires_user_approval = $requiresUserApproval
    requires_user_approval_for_actual_collect = $requiresUserApprovalForActualCollect
    primary_command = $primaryCommand
    allowed_actions = $allowedActions
    blocked_actions = $blockedActions
    state = [ordered]@{
        gate_status = $gate.status
        gate_run_id = $gate.run_id
        gate_completed_cycles = $gate.completed_cycles
        gate_total_cycles = $gate.total_cycles
        gate_rows = $gate.rows
        gate_errors = $gate.errors
        gate_warning = $gate.warning
        gate_next_step_after_ready = $gate.next_step_after_ready
        gate_raw_next_step_after_ready = $gate.raw_gate_next_step_after_ready
        gate_postprocess_block = $gate.postprocess_block
        preflight_status = $preflight.status
        preflight_ok = $preflight.ok
        preflight_fail_count = $preflight.fail_count
        preflight_warn_count = $preflight.warn_count
        acceptance_stage = $acceptance.stage
        strategy_accepted = $acceptance.accepted
        live_orders = $acceptance.live_orders
        sweep_reversal_gate_accepted = $sweepReversalGate.accepted
        sweep_reversal_gate_decision = $sweepReversalGate.decision
        sweep_reversal_gate_fail_count = $sweepReversalGate.fail_count
        sweep_reversal_gate_reasons = @($sweepReversalGate.reasons)
        objective_focus = $goalStatus.objective_focus
        objective_source_of_truth = $goalStatus.objective_source_of_truth
        stale_internal_goal_handling = $goalStatus.stale_internal_goal_handling
        channel_intake = $goalStatus.channel_intake
        accepted_trading_strategies = $goalStatus.accepted_trading_strategies
        primary_edge_status = $goalStatus.primary_edge_status
        funding_blocked_by_swarm = $fundingBlockedBySwarm
        liquidity_sweep_rejected_gate = $liquiditySweepRejectedGate
        funding_rejected_base_fees_gate = $fundingRejectedBaseFeesGate
        cross_venue_rejected_gate = $crossVenueRejectedGate
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
        slow_liquidity_exact_recollect_awaiting_approval_gate = $slowLiquidityExactRecollectAwaitingApprovalGate
        slow_liquidity_exact_recollect_integrity_blocked_gate = $slowLiquidityExactRecollectIntegrityBlockedGate
        slow_liquidity_exact_recollect_plan_path = [string]$slowLiquidityExactRecollectStatus.plan_path
        slow_liquidity_exact_recollect_plan_hash = [string]$slowLiquidityExactRecollectStatus.plan_hash
        slow_liquidity_exact_recollect_plan_file_sha256 = [string]$slowLiquidityExactRecollectStatus.plan_file_sha256
        slow_liquidity_exact_recollect_receipt_present = [bool]$slowLiquidityExactRecollectStatus.receipt_present
        slow_liquidity_exact_recollect_launch_record_present = [bool]$slowLiquidityExactRecollectStatus.launch_record_present
        slow_liquidity_exact_recollect_output_present = [bool]$slowLiquidityExactRecollectStatus.output_present
        slow_liquidity_exact_recollect_errors = @($slowLiquidityExactRecollectStatus.errors)
        slow_liquidity_data_availability_ready_gate = $slowLiquidityDataAvailabilityReadyGate
        slow_liquidity_data_availability_accepted_gate = $slowLiquidityDataAvailabilityAcceptedGate
        slow_liquidity_data_availability_rejected_gate = $slowLiquidityDataAvailabilityRejectedGate
            slow_liquidity_history_data_plan_ready_gate = $slowLiquidityHistoryDataPlanReadyGate
            slow_liquidity_history_quality_accepted_gate = $slowLiquidityHistoryQualityAcceptedGate
            slow_liquidity_fixed_signal_ready_gate = $slowLiquidityFixedSignalReadyGate
            slow_liquidity_feature_normalizer_ready_gate = $slowLiquidityFeatureNormalizerReadyGate
            slow_liquidity_feature_normalizer_rejected_gate = $slowLiquidityFeatureNormalizerRejectedGate
            slow_liquidity_v0_rejected_ready_for_census_gate = $slowLiquidityV0RejectedReadyForCensusGate
            slow_liquidity_event_census_accepted_gate = $slowLiquidityEventCensusAcceptedGate
            slow_liquidity_event_census_rejected_gate = $slowLiquidityEventCensusRejectedGate
            slow_liquidity_fixed_v1_ready_gate = $slowLiquidityFixedV1ReadyGate
            slow_liquidity_replay_v1_candidate_gate = $slowLiquidityReplayV1CandidateGate
            slow_liquidity_replay_v1_rejected_gate = $slowLiquidityReplayV1RejectedGate
        swarm_status = if ($swarmStatus) { [string]$swarmStatus.status } else { "NO_SWARM_STATUS" }
        swarm_limited = $swarmLimited
        swarm_independent_review_available = [bool]($swarmStatus -and [bool]$swarmStatus.independent_review_available)
        swarm_latest_workflow_id = $swarmLatestWorkflowId
        swarm_recommended_action = $swarmRecommendedAction
        fee_tier_evidence_present = $feeTierEvidencePresent
    }
    commands = [ordered]@{
        gate_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
        edge_preflight = $preflightCommand
        swarm_status = "pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json"
        trading_test_runner_plan = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript -PlanOnly -Json"
        trading_test_full = "pwsh -NoProfile -ExecutionPolicy Bypass -File $tradingTestRunnerScript"
        strategy_acceptance_gate = $acceptanceCommand
        funding_viability_gap = $fundingGapCommand
        funding_cost_assumption_gate = $fundingCostGateCommand
        funding_candidate_watchlist = $fundingCandidateWatchlistCommand
        funding_watchlist_review = $fundingWatchlistReviewCommand
        funding_basis_planonly = $fundingBasisPlanOnlyCommand
        structural_branch_planonly = $structuralBranchPlanOnlyCommand
        structural_branch_planonly_update_gate = $structuralBranchPlanOnlyUpdateGateCommand
        slow_liquidity_regime_planonly = $slowLiquidityPlanOnlyCommand
        slow_liquidity_regime_planonly_update_gate = $slowLiquidityPlanOnlyUpdateGateCommand
        slow_liquidity_data_availability_preflight = $slowLiquidityDataAvailabilityPreflightCommand
        slow_liquidity_data_availability_preflight_update_gate = $slowLiquidityDataAvailabilityPreflightUpdateGateCommand
        slow_liquidity_history_data_plan = $slowLiquidityHistoryPlanCommand
        slow_liquidity_history_data_plan_update_gate = $slowLiquidityHistoryPlanUpdateGateCommand
        slow_liquidity_fixed_signal_plan = $slowLiquidityFixedSignalPlanCommand
        slow_liquidity_fixed_signal_plan_update_gate = $slowLiquidityFixedSignalPlanUpdateGateCommand
        slow_liquidity_feature_normalizer = $slowLiquidityFeatureNormalizerCommand
        slow_liquidity_feature_normalizer_update_gate = $slowLiquidityFeatureNormalizerUpdateGateCommand
        slow_liquidity_rescope_planonly = $slowLiquidityRescopePlanOnlyCommand
        slow_liquidity_rescope_planonly_update_gate = $slowLiquidityRescopePlanOnlyUpdateGateCommand
        slow_liquidity_event_census_v1_planonly = $slowLiquidityEventCensusCommand
        slow_liquidity_event_census_v1_planonly_update_gate = $slowLiquidityEventCensusUpdateGateCommand
        slow_liquidity_fixed_v1_planonly = $slowLiquidityFixedV1PlanCommand
        slow_liquidity_fixed_v1_planonly_update_gate = $slowLiquidityFixedV1PlanUpdateGateCommand
        slow_liquidity_replay_v1_planonly = $slowLiquidityReplayV1Command
        slow_liquidity_replay_v1_planonly_update_gate = $slowLiquidityReplayV1UpdateGateCommand
        slow_liquidity_exact_recollect_preflight = $slowLiquidityExactRecollectPreflightCommand
        slow_liquidity_exact_recollect_approval_packet = $slowLiquidityExactRecollectApprovalPacketCommand
        spot_perp_basis_mean_reversion_planonly = $spotPerpBasisPlanOnlyCommand
        spot_perp_basis_availability_preflight = $spotPerpBasisAvailabilityPreflightCommand
        spot_perp_basis_availability_preflight_update_gate = $spotPerpBasisAvailabilityPreflightUpdateGateCommand
        spot_perp_basis_public_probe_plan = $spotPerpBasisPublicProbePlanCommand
        spot_perp_basis_public_probe_after_confirmation = $spotPerpBasisPublicProbeConfirmedCommand
        listing_event_planonly = $listingEventPlanOnlyCommand
        listing_event_planonly_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventPlanOnlyScript -UpdateGate -Json"
        listing_event_normalizer_planonly = $listingEventNormalizerPlanOnlyCommand
        listing_event_normalizer_planonly_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventNormalizerPlanOnlyScript -UpdateGate -Json"
        listing_event_history_planonly = $listingEventHistoryPlanOnlyCommand
        listing_event_history_planonly_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -UpdateGate -Json"
        listing_event_history_collect_preview = $listingEventHistoryCollectPreviewCommand
        listing_event_history_collect_preview_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectPreviewScript -UpdateGate -Json"
        listing_event_history_collect_preview_planonly = $listingEventHistoryCollectPreviewPlanOnlyCommand
        listing_event_history_collect_approval_packet = $listingEventHistoryCollectApprovalPacketCommand
        listing_event_history_collect_visible_plan = $listingEventHistoryCollectVisiblePlanCommand
        listing_event_history_collect_visible_after_approval = $listingEventHistoryCollectVisibleCommand
        listing_event_history_data_quality = $listingEventHistoryDataQualityCommand
        listing_event_history_data_quality_update_gate = $listingEventHistoryDataQualityUpdateGateCommand
        listing_event_history_recollect_plan = $listingEventHistoryRecollectPlanCommand
        listing_event_history_availability_preflight = $listingEventHistoryAvailabilityPreflightCommand
        listing_event_history_availability_preflight_update_gate = $listingEventHistoryAvailabilityPreflightUpdateGateCommand
        listing_event_history_availability_public_probe_after_confirmation = $listingEventHistoryAvailabilityPublicProbeCommand
        listing_event_replay_planonly = $listingEventReplayPlanOnlyCommand
        branch_selector = "pwsh -NoProfile -ExecutionPolicy Bypass -File $branchSelectorScript"
        sweep_reversal_acceptance_gate = $sweepReversalGateCommand
        visible_ws_collect_preview = $visibleWsCollectPreviewCommand
        visible_ws_collect_preview_shortcut = $previewDenseWsShortcut
        visible_ws_collect_after_approval = $visibleWsCollectCommand
        visible_ws_collect_command_resolution = $visibleWsCollectCommandResolution
        visible_ws_collect_readiness = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectReadinessScript -Json"
        collect_approval_contract = "pwsh -NoProfile -ExecutionPolicy Bypass -File $collectApprovalContractScript -Json"
        ws_collect_approval_packet = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectApprovalPacketScript -Json"
        visible_ws_collect_plan_preview_latest = $visibleWsPlanPreviewLatest
        visible_ws_collect_confirmed_shortcut = $startDenseWsShortcut
        ws_postprocess_from_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsPostprocessScript"
        ws_postprocess_from_gate_shortcut = $wsPostprocessShortcut
        ws_replay_validation_plan = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsReplayValidationScript -PostprocessPath <exports\trading-mvp\backtests\ws_postprocess_*.json> -ExpectedManifestPath <exports\trading-mvp\raw\ws_collect_*.json> -PlanOnly"
        ws_replay_validation_after_review = "pwsh -NoProfile -ExecutionPolicy Bypass -File $wsReplayValidationScript -PostprocessPath <exports\trading-mvp\backtests\ws_postprocess_*.json> -ExpectedManifestPath <exports\trading-mvp\raw\ws_collect_*.json> -ConfirmedResearchRun"
        research_goal_plan = $researchGoalPlanPath
        fee_tier_evidence = $feeTierEvidencePath
        public_fee_observations = $publicFeeObservationsPath
        funding_visible_collect_preview = $visibleFundingCollectPreviewCommand
        funding_visible_collect_after_approval = $visibleFundingCollectCommand
        funding_visible_collect_preview_shortcut = $preview7dFundingShortcut
        funding_visible_collect_confirmed_shortcut = $start7dFundingShortcut
        visible_collect_legacy_resolution = $visibleCollectLegacyResolution
        visible_collect_preview = $visibleCollectPreviewCommand
        visible_collect_preview_shortcut = $visibleCollectPreviewShortcut
        visible_collect_after_approval = $visibleCollectCommand
        visible_collect_confirmed_shortcut = $visibleCollectConfirmedShortcut
        final_review_after_final_manifest = $finalReviewCommand
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "trading_mvp Next Goal Step" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Decision: $decision"
Write-Host "Requires user approval: $requiresUserApproval"
Write-Host "Reason: $reason"
Write-Host ""

Write-Host "State" -ForegroundColor Yellow
Write-Host "  Gate: $($result.state.gate_status), cycles=$($result.state.gate_completed_cycles)/$($result.state.gate_total_cycles), rows=$($result.state.gate_rows), errors=$($result.state.gate_errors)"
Write-Host "  Preflight: $($result.state.preflight_status), ok=$($result.state.preflight_ok), failures=$($result.state.preflight_fail_count), warnings=$($result.state.preflight_warn_count)"
Write-Host "  Acceptance: $($result.state.acceptance_stage), accepted=$($result.state.strategy_accepted), live_orders=$($result.state.live_orders)"
Write-Host "  Objective source: $($result.state.objective_source_of_truth)"
Write-Host "  Stale goal handling: $($result.state.stale_internal_goal_handling)"
Write-Host "  Channel intake: $($result.state.channel_intake)"
Write-Host "  Accepted trading strategies: $($result.state.accepted_trading_strategies)"
Write-Host "  Funding blocked by swarm: $($result.state.funding_blocked_by_swarm)"
Write-Host "  Liquidity sweep rejected gate: $($result.state.liquidity_sweep_rejected_gate)"
Write-Host "  Swarm status: $($result.state.swarm_status)"
Write-Host "  Swarm limited: $($result.state.swarm_limited)"
Write-Host "  Swarm latest workflow: $($result.state.swarm_latest_workflow_id)"
Write-Host "  Swarm recommended action: $($result.state.swarm_recommended_action)"
Write-Host "  Fee-tier evidence present: $($result.state.fee_tier_evidence_present)"
Write-Host ""

Write-Host "Allowed actions" -ForegroundColor Yellow
foreach ($action in $allowedActions) {
    Write-Host "  - $action"
}
Write-Host ""

Write-Host "Blocked actions" -ForegroundColor Yellow
foreach ($action in $blockedActions) {
    Write-Host "  - $action"
}
Write-Host ""

Write-Host "Primary command" -ForegroundColor Yellow
Write-Host "  $primaryCommand"
Write-Host ""
Write-Host "Status commands"
Write-Host "  $($result.commands.gate_status)"
Write-Host "  $($result.commands.edge_preflight)"
Write-Host "  $($result.commands.swarm_status)"
Write-Host "  $($result.commands.trading_test_runner_plan)"
Write-Host "  $($result.commands.trading_test_full)"
Write-Host "  $($result.commands.strategy_acceptance_gate)"
Write-Host "  $($result.commands.funding_viability_gap)"
Write-Host "  $($result.commands.funding_cost_assumption_gate)"
Write-Host "  $($result.commands.funding_candidate_watchlist)"
Write-Host "  $($result.commands.funding_watchlist_review)"
Write-Host "  $($result.commands.funding_basis_planonly)"
Write-Host "  $($result.commands.structural_branch_planonly)"
Write-Host "  $($result.commands.branch_selector)"
Write-Host "  $($result.commands.sweep_reversal_acceptance_gate)"
Write-Host "  $($result.commands.visible_ws_collect_preview)"
Write-Host "  $($result.commands.visible_ws_collect_readiness)"
Write-Host "  $($result.commands.visible_ws_collect_preview_shortcut)"
Write-Host "  $($result.commands.visible_ws_collect_after_approval)"
Write-Host "  $($result.commands.visible_ws_collect_confirmed_shortcut)"
Write-Host "  approval contract before START72H: $($result.commands.collect_approval_contract)"
Write-Host "  approval packet before START72H: $($result.commands.ws_collect_approval_packet)"
Write-Host "  $($result.commands.ws_postprocess_from_gate)"
Write-Host "  $($result.commands.ws_postprocess_from_gate_shortcut)"
Write-Host "  $($result.commands.ws_replay_validation_plan)"
Write-Host "  $($result.commands.ws_replay_validation_after_review)"
Write-Host "  Research goal plan: $($result.commands.research_goal_plan)"
Write-Host "  Fee-tier evidence: $($result.commands.fee_tier_evidence)"
Write-Host "  Public fee observations: $($result.commands.public_fee_observations)"
Write-Host ""
Write-Host "Visible dense WS collect commands"
Write-Host "  preview: $($result.commands.visible_ws_collect_preview)"
Write-Host "  readiness: $($result.commands.visible_ws_collect_readiness)"
Write-Host "  approval contract: $($result.commands.collect_approval_contract)"
Write-Host "  approval packet: $($result.commands.ws_collect_approval_packet)"
Write-Host "  preview shortcut: $($result.commands.visible_ws_collect_preview_shortcut)"
Write-Host "  start after explicit approval: $($result.commands.visible_ws_collect_after_approval)"
Write-Host "  start shortcut with START72H prompt: $($result.commands.visible_ws_collect_confirmed_shortcut)"
Write-Host "  postprocess after finished collect: $($result.commands.ws_postprocess_from_gate)"
Write-Host "  postprocess shortcut: $($result.commands.ws_postprocess_from_gate_shortcut)"
Write-Host "  replay validation plan after accepted postprocess: $($result.commands.ws_replay_validation_plan)"
Write-Host "  replay validation after explicit review: $($result.commands.ws_replay_validation_after_review)"
Write-Host ""
Write-Host "Legacy visible_collect commands"
Write-Host "  resolution: $($result.commands.visible_collect_legacy_resolution)"
Write-Host "  preview: $($result.commands.visible_collect_preview)"
Write-Host "  start after explicit approval: $($result.commands.visible_collect_after_approval)"
Write-Host ""
Write-Host "Visible 7d funding collect commands, not the current primary branch after swarm block"
Write-Host "  preview: $($result.commands.funding_visible_collect_preview)"
Write-Host "  preview shortcut: $($result.commands.funding_visible_collect_preview_shortcut)"
Write-Host "  start after fee/economics branch is reopened and explicit approval: $($result.commands.funding_visible_collect_after_approval)"
Write-Host "  start shortcut with START7D prompt: $($result.commands.funding_visible_collect_confirmed_shortcut)"
