param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$preflightScript = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$acceptanceGateScript = Join-Path $repoRoot "tools\trading_strategy_acceptance_gate.ps1"
$scorecardPath = Join-Path $repoRoot "exports\trading-mvp\analysis\anufriev_strategy_scorecard_current_20260628.csv"
$branchDecisionPath = Join-Path $repoRoot "exports\trading-mvp\analysis\trading_edge_branch_decision_20260627.json"
$feeTierEvidencePath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_account_fee_tiers_current.json"
$fundingCostAssumptionGateScript = Join-Path $repoRoot "tools\funding_cost_assumption_gate.ps1"
$visibleWsCollectScript = Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"
$visibleWsPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"
$visibleWsLegacyPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_6h_plan_preview_latest.json"
if ((-not (Test-Path -LiteralPath $visibleWsPlanPreviewLatest)) -and (Test-Path -LiteralPath $visibleWsLegacyPlanPreviewLatest)) {
    $visibleWsPlanPreviewLatest = $visibleWsLegacyPlanPreviewLatest
}
$visibleWsPreviewShortcut = Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"
$visibleWsConfirmedShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"
$sweepReversalGateScript = Join-Path $repoRoot "tools\sweep_reversal_acceptance_gate.ps1"
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
$pitUniverseVisibleCollectScript = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"
$pitCrossVenueScreenVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_screen_visible.ps1"
$pitCrossVenueForwardOosVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_forward_oos_visible.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$crossVenueFullOutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"

function Invoke-JsonScript {
    param([string]$Path)
    return (& pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -Json | ConvertFrom-Json)
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

function To-NullableDouble {
    param($Value)
    if ($null -eq $Value) {
        return $null
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text) -or $text -eq "not-applicable") {
        return $null
    }
    $parsed = 0.0
    if ([double]::TryParse($text, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return $parsed
    }
    return $null
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

function Get-ScorecardRow {
    param(
        [object[]]$Rows,
        [string]$Family
    )
    return ($Rows | Where-Object { $_.strategy_family -eq $Family } | Select-Object -First 1)
}

function Convert-RowSummary {
    param($Row)
    if ($null -eq $Row) {
        return $null
    }
    return [ordered]@{
        strategy_family = $Row.strategy_family
        project_setup_id = $Row.project_setup_id
        verdict = $Row.verdict
        win_rate = $Row.win_rate
        trades = $Row.trades
        net_pnl_quote = $Row.net_pnl_quote
        profit_factor = $Row.profit_factor
        key_metric_summary = $Row.key_metric_summary
        economic_status = $Row.economic_status
        next_action = $Row.next_action
        evidence = $Row.evidence
    }
}

$gate = Invoke-JsonScript -Path $gateChecker
$rawGate = Read-JsonFileOrNull -Path $gatePath
$featureNormalizerArtifact = if ($rawGate -and [string]$rawGate.last_slow_liquidity_feature_normalizer_output_path) {
    Read-JsonFileOrNull -Path ([string]$rawGate.last_slow_liquidity_feature_normalizer_output_path)
} else {
    $null
}
$slowLiquidityFeatureNormalizerArtifactIsV1 = [bool]($featureNormalizerArtifact -and $featureNormalizerArtifact.fixed_contract -and $featureNormalizerArtifact.fixed_contract.signal -and [string]$featureNormalizerArtifact.fixed_contract.signal.compression_metric -eq "range_width_over_atr_sqrt_lookback")
$forwardOosApprovalReadyFastPath = [string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"
if ($forwardOosApprovalReadyFastPath) {
    $command = if ($gate.command_after_explicit_approval) {
        [string]$gate.command_after_explicit_approval
    } else {
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueForwardOosVisibleScript`" -PlanPath `"$($rawGate.forward_oos_plan_path)`" -ConfirmedForwardOosCollect"
    }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_branch_selector"
        decision = "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION"
        selected_branch = "pit_linear_perp_cross_venue_forward_oos"
        reason = "The spot branch remains rejected. A separately labelled linear-perp public probe passed the data-path gate and produced a sealed forward-OOS plan; no strategy is accepted."
        requires_user_approval = $true
        requires_user_approval_for_immediate_work = $true
        requires_user_approval_for_actual_collect = $true
        research_accepted = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        allowed_immediate_work = @("inspect_planonly", "explicitly_confirm_visible_forward_oos_collect", "status_checks")
        blocked_work = @(
            "automatic_collect_start",
            "spot_interpretation",
            "reuse_discovery_as_oos",
            "replay",
            "backtest",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys"
        )
        primary_command = $command
        plan_path = if ($rawGate) { $rawGate.forward_oos_plan_path } else { $null }
        plan_sha256 = if ($rawGate) { $rawGate.forward_oos_plan_sha256 } else { $null }
        fast_path = [ordered]@{ reason = "forward_oos_approval_packet_ready"; raw_gate_path = $gatePath }
    }
    if ($Json) { $result | ConvertTo-Json -Depth 10; exit 0 }
    Write-Host "Trading branch selector" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Selected branch: $($result.selected_branch)"
    Write-Host "Explicit confirmation required: True"
    exit 0
}
$pitLinearPerpScreenReadyFastPath = [string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"
if ($pitLinearPerpScreenReadyFastPath) {
    $screenCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueScreenVisibleScript`" -ConfirmedResearchScreen -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_branch_selector"
        decision = "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"
        selected_branch = "pit_linear_perp_cross_venue_screening"
        reason = "The prior spot branch remains rejected. Existing PIT data can only support a separately labelled linear-perp screening report through the hashed whole-cycle mask."
        requires_user_approval = $false
        requires_user_approval_for_immediate_work = $false
        requires_user_approval_for_actual_collect = $false
        research_accepted = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        allowed_immediate_work = @(
            "run_visible_streaming_linear_perp_screen",
            "verify_source_and_mask_hashes",
            "preserve_no_strategy_accepted"
        )
        blocked_work = @(
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
        artifacts = [ordered]@{
            clean_slice_spec = if ($rawGate) { $rawGate.last_pit_two_venue_clean_slice_spec_path } else { $null }
            mask_sha256 = if ($rawGate) { $rawGate.last_pit_two_venue_clean_slice_mask_sha256 } else { $null }
            visible_screen_command = $screenCommand
            active_run_gate = $gatePath
        }
        gate_summary = [ordered]@{
            status = $gate.status
            run_id = $gate.run_id
            replay_allowed = $gate.replay_allowed
            next_goal_decision = $gate.next_goal_decision
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
    Write-Host "trading_mvp Branch Selector" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Selected branch: $($result.selected_branch)"
    Write-Host "Command: $screenCommand"
    exit 0
}
$pitUniverseCollectReadyFastPath = (
    ([string]$gate.next_goal_decision -eq "START_NEW_VISIBLE_PIT_UNIVERSE_SNAPSHOT_COLLECT_AFTER_FIX_APPROVAL") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gate.strategy_branch_status.verdict -eq "control_plane_fixed_ready_for_new_clean_collect_approval"
    )
)

if ($pitUniverseCollectReadyFastPath) {
    $pitPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseVisibleCollectScript -Hours 24 -IntervalSec 300 -TimeoutSec 10 -MinContractsPerExchange 50 -OutputRoot E:\trading_mvp\pit-universe-snapshots -PlanOnly -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_branch_selector"
        decision = "PIT_UNIVERSE_SNAPSHOT_COLLECT_AWAITING_EXPLICIT_CONFIRMATION"
        selected_branch = "forward_pit_universe_event_liquidity_anomaly"
        reason = "The prior pre-v2 PIT run is rejected. The only valid next branch action is a new clean visible PIT v2 collect after explicit approval."
        requires_user_approval = $true
        requires_user_approval_for_immediate_work = $true
        requires_user_approval_for_actual_collect = $true
        command_after_explicit_approval = ""
        pit_universe_collect_ready_gate = $true
        funding_blocked_by_swarm = $false
        research_accepted = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        allowed_immediate_work = @(
            "await_explicit_confirmation_for_visible_pit_snapshot_collect",
            "run_pit_universe_visible_collect_planonly",
            "keep_replay_grid_live_api_and_paper_forward_blocked"
        )
        blocked_work = @(
            "resume_old_pre_v2_pit_run",
            "actual_collect_without_explicit_confirmation",
            "replay",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin"
        )
        selected_evidence = [ordered]@{
            funding = $null
            spot_maker_liquidity_sweep_reversal = $null
            sweep_reclaim_event_quality_layer = $null
            perp_microstructure = $null
            breakout_momentum = $null
        }
        artifacts = [ordered]@{
            scorecard = $scorecardPath
            branch_decision = $branchDecisionPath
            fee_tier_evidence = $feeTierEvidencePath
            pit_universe_visible_collect_planonly_command = $pitPlanCommand
            active_run_gate = $gatePath
        }
        gate_summary = [ordered]@{
            status = $gate.status
            run_id = $gate.run_id
            rows = $gate.rows
            errors = $gate.errors
            replay_allowed = $gate.replay_allowed
            next_goal_decision = $gate.next_goal_decision
            next_step_after_ready = $gate.next_step_after_ready
        }
        fast_path = [ordered]@{
            reason = "current_pit_gate_overrides_historical_branch_flags"
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }
    if ($Json) {
        $result | ConvertTo-Json -Depth 10
        exit 0
    }
    Write-Host "trading_mvp Branch Selector" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Selected branch: $($result.selected_branch)"
    Write-Host "PlanOnly command: $pitPlanCommand"
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
    $selectedBranch = "spot_perp_basis_mean_reversion_no_funding"
    $reason = "spot/perp basis availability preflight is ready for a short visible public REST probe, but explicit user confirmation is required. No actual collect, replay, grid, live orders, API keys, leverage, margin or paper-forward."
    $allowedImmediateWork = @(
        "await_explicit_confirmation_for_short_public_spot_perp_availability_probe",
        "read_command_after_explicit_approval",
        "keep_collect_grid_replay_live_api_and_paper_forward_blocked",
        "keep_funding_as_risk_filter_not_pnl_source"
    )
    $blockedWork = @(
        "actual_collect_without_explicit_confirmation",
        "backtest_or_replay",
        "grid_search",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward_without_accepted_research",
        "new_hidden_or_background_long_run"
    )
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_branch_selector"
        decision = $decision
        selected_branch = $selectedBranch
        reason = $reason
        requires_user_approval = $true
        requires_user_approval_for_immediate_work = $true
        requires_user_approval_for_actual_collect = $true
        command_after_explicit_approval = $spotPerpBasisPublicProbeConfirmedCommand
        funding_blocked_by_swarm = $false
        fee_tier_evidence_present = Test-Path -LiteralPath $feeTierEvidencePath
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
        gate_status = $gate.status
        acceptance_stage = "skipped_fast_path"
        research_accepted = $false
        live_orders = $false
        allowed_immediate_work = $allowedImmediateWork
        blocked_work = $blockedWork
        next_proof_gates = @(
            "explicit_user_confirmation_before_public_probe",
            "paired_spot_perp_coverage",
            "usable_spread_and_depth",
            "no_replay_until_probe_accepts_coverage",
            "no_grid_live_api_or_paper_forward"
        )
        selected_evidence = [ordered]@{
            funding = $null
            spot_maker_liquidity_sweep_reversal = $null
            sweep_reclaim_event_quality_layer = $null
            perp_microstructure = $null
            breakout_momentum = $null
        }
        artifacts = [ordered]@{
            scorecard = $scorecardPath
            branch_decision = $branchDecisionPath
            fee_tier_evidence = $feeTierEvidencePath
            spot_perp_basis_public_probe = $spotPerpBasisPublicProbeScript
            spot_perp_basis_public_probe_plan_command = $spotPerpBasisPublicProbePlanCommand
            spot_perp_basis_public_probe_after_confirmation_command = $spotPerpBasisPublicProbeConfirmedCommand
        }
        gate_summary = [ordered]@{
            status = $gate.status
            run_id = $gate.run_id
            rows = $gate.rows
            errors = $gate.errors
            primary_output_complete = $gate.primary_output_complete
            expected_outputs_complete = $gate.expected_outputs_complete
            replay_allowed = $gate.replay_allowed
            next_goal_decision = $gate.next_goal_decision
            next_step_after_ready = $gate.next_step_after_ready
        }
        fast_path = [ordered]@{
            reason = "active_gate_already_requires_explicit_public_probe_confirmation"
            skipped_scripts = @(
                $preflightScript,
                $acceptanceGateScript
            )
            raw_gate_path = $gatePath
            raw_gate_loaded = [bool]$rawGate
        }
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 10
        exit 0
    }

    Write-Host "trading_mvp Branch Selector" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Decision: $decision"
    Write-Host "Selected branch: $selectedBranch"
    Write-Host "Reason: $reason"
    Write-Host "Requires user approval now: True"
    Write-Host "Command after explicit approval:"
    Write-Host "  $spotPerpBasisPublicProbeConfirmedCommand"
    exit 0
}

$preflight = Invoke-JsonScript -Path $preflightScript
$acceptance = Invoke-JsonScript -Path $acceptanceGateScript
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
$scorecard = Read-CsvSafe -Path $scorecardPath
$branchDecision = $null
if (Test-Path -LiteralPath $branchDecisionPath) {
    $branchDecision = Get-Content -Raw -LiteralPath $branchDecisionPath | ConvertFrom-Json
}

$fundingBlocked = $false
if ($preflight.PSObject.Properties.Name -contains "funding_blocked_by_swarm") {
    $fundingBlocked = [bool]$preflight.funding_blocked_by_swarm
}
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
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_NORMALIZER_PLANONLY_INSUFFICIENT_OVERLAP_NEEDS_EVENT_OHLCV_HISTORY") -or
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_PLANONLY_READY_FOR_VISIBLE_HISTORY_COLLECT_APPROVAL") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_HISTORY_COLLECT_PREVIEW*") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT*") -or
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY") -or
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_NORMALIZER") -or
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN") -or
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
        [string]$gate.strategy_branch_status.verdict -in @("feature_normalizer_rejected_insufficient_events", "feature_normalizer_v1_rejected_insufficient_events")
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
$visibleWsCollectCommandResolution = Resolve-WsCollectCommands -ScriptPath $visibleWsCollectScript -PlanPreviewPath $visibleWsPlanPreviewLatest
$visibleWsCollectPreviewCommand = [string]$visibleWsCollectCommandResolution.preview_command
$visibleWsCollectCommand = [string]$visibleWsCollectCommandResolution.command
$visibleWsCollectRequiresUserApproval = [bool]($visibleWsCollectCommand -match "-ConfirmedLongRun")
$requiresUserApprovalForActualCollect = $visibleWsCollectRequiresUserApproval

$spotSweep = Get-ScorecardRow -Rows $scorecard -Family "Spot maker liquidity sweep/reversal"
$eventQuality = Get-ScorecardRow -Rows $scorecard -Family "Sweep/reclaim event-quality layer"
$perpSignals = Get-ScorecardRow -Rows $scorecard -Family "Perp long/short microstructure current signal family"
$breakout = Get-ScorecardRow -Rows $scorecard -Family "Large-move breakout momentum"
$funding = Get-ScorecardRow -Rows $scorecard -Family "Funding/basis carry current cost model"

$decision = "MANUAL_REVIEW_REQUIRED"
$selectedBranch = $null
$reason = ""
$requiresUserApproval = $false
$allowedImmediateWork = @()
$blockedWork = @(
    "live_orders",
    "api_keys",
    "leverage_or_margin",
    "paper_forward_without_accepted_research",
    "new_hidden_or_background_long_run",
    "new_channel_or_p2p_content_analysis",
    "retune_rejected_signals_on_same_thin_sample"
)

if ([string]$gate.status -eq "RUNNING") {
    $decision = "STATUS_ONLY"
    $reason = "Active run gate is RUNNING; only status/ETA checks are allowed."
    $allowedImmediateWork = @("status_eta_check")
} elseif ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
    $decision = "RESUME_OR_REJECT_INCOMPLETE_DATASET"
    $reason = "Active run gate is STOPPED_INCOMPLETE; resume visibly or reject the dataset before choosing a branch."
    $requiresUserApproval = $true
    $allowedImmediateWork = @("visible_resume_current_run", "declare_dataset_incomplete")
} elseif ([bool]$acceptance.accepted) {
    $decision = "PAPER_FORWARD_GATE_REQUIRED"
    $reason = "A research setup appears accepted; paper-forward planning is required and live remains blocked."
    $requiresUserApproval = $true
    $allowedImmediateWork = @("freeze_config", "prepare_visible_paper_forward_plan")
} elseif ($slowLiquiditySelectedGate) {
    $decision = if ($slowLiquidityFeatureNormalizerReadyGate) {
        "SLOW_LIQUIDITY_FEATURE_NORMALIZER_READY_FOR_FIXED_REPLAY_VALIDATION"
    } elseif ($slowLiquidityFeatureNormalizerRejectedGate -and $slowLiquidityFeatureNormalizerArtifactIsV1) {
        "SLOW_LIQUIDITY_FEATURE_NORMALIZER_V1_REJECTED_SELECT_NEXT_BRANCH"
    } elseif ($slowLiquidityFeatureNormalizerRejectedGate) {
        "SLOW_LIQUIDITY_FEATURE_NORMALIZER_REJECTED_RESCOPE_OR_LARGER_HISTORY"
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
        "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_RESEARCH"
    }
    $selectedBranch = "slow_liquidity_regime_breakout_retest"
    $reason = if ($slowLiquidityFeatureNormalizerReadyGate) {
        "slow_liquidity_regime_breakout_retest feature normalizer is ready. Next work is fixed-parameter replay-validation PlanOnly; no grid, live, API keys, leverage or paper-forward."
    } elseif ($slowLiquidityFeatureNormalizerRejectedGate -and $slowLiquidityFeatureNormalizerArtifactIsV1) {
        "slow_liquidity scaled-compression v1 is rejected for insufficient independent events. A materially new structural hypothesis needs an explicit user checkpoint; do not retune or recollect under v1."
    } elseif ($slowLiquidityFeatureNormalizerRejectedGate) {
        "slow_liquidity_regime_breakout_retest feature normalizer rejected the fixed v0 event set as insufficient. Do not replay/grid; rescope/reject branch or plan larger independent history."
    } elseif ($slowLiquidityFixedSignalReadyGate) {
        "slow_liquidity_regime_breakout_retest fixed v0 signal contract is ready. Next work is feature normalizer PlanOnly on clean 1h/4h two-venue slice; no grid, replay, live, API keys, leverage or paper-forward until normalizer exists."
    } elseif ($slowLiquidityHistoryQualityAcceptedGate) {
        "slow_liquidity_regime_breakout_retest history data-quality accepted. Next work is fixed-v0 signal contract PlanOnly; no grid, replay, live, API keys, leverage or paper-forward."
    } elseif ($slowLiquidityHistoryDataPlanReadyGate) {
        "slow_liquidity_regime_breakout_retest history data plan is ready. Await explicit approval before implementing/running visible public OHLCV history collect; no replay, grid, live, API keys, leverage or paper-forward."
    } elseif ($slowLiquidityDataAvailabilityRejectedGate) {
        "slow_liquidity_regime_breakout_retest data availability preflight rejected current local data. Next work is a history data plan/approval packet only; no collect, grid, replay, live, API keys, leverage or paper-forward."
    } elseif ($slowLiquidityDataAvailabilityAcceptedGate) {
        "slow_liquidity_regime_breakout_retest data availability preflight accepted raw coverage. Next work is fixed-v0 signal contract PlanOnly; no grid, replay, live, API keys, leverage or paper-forward."
    } else {
        "slow_liquidity_regime_breakout_retest is selected after spot/perp public-probe rejection. Next work is a read-only PlanOnly data availability preflight and fixed-v0 signal contract; no collect, grid, replay, live, API keys, leverage or paper-forward."
    }
    $requiresUserApproval = [bool](
        $slowLiquidityHistoryDataPlanReadyGate -or
        ($slowLiquidityFeatureNormalizerRejectedGate -and $slowLiquidityFeatureNormalizerArtifactIsV1)
    )
    $requiresUserApprovalForActualCollect = [bool]$slowLiquidityHistoryDataPlanReadyGate
    $allowedImmediateWork = @(
        "run_slow_liquidity_regime_breakout_retest_planonly",
        "run_slow_liquidity_data_availability_preflight_planonly",
        "run_slow_liquidity_fixed_signal_planonly",
        "run_slow_liquidity_feature_normalizer_planonly",
        "await_explicit_user_approval_for_new_structural_hypothesis",
        "run_fixed_slow_liquidity_replay_validation_planonly_when_normalizer_allows",
        "build_slow_liquidity_feature_normalizer_planonly",
        "build_slow_liquidity_data_availability_preflight_planonly",
        "build_slow_liquidity_history_data_plan_approval_packet_planonly",
        "await_explicit_user_approval_for_slow_liquidity_history_collect",
        "define_fixed_v0_regime_signal_before_replay",
        "keep_collect_grid_replay_live_api_and_paper_forward_blocked"
    )
} elseif ($spotPerpBasisAvailabilityRejectedGate) {
    $decision = if ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") { "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE" } else { "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_RESCOPE" }
    $selectedBranch = "next_non_hft_structural_branch"
    $reason = "spot_perp_basis_mean_reversion_no_funding availability/public probe is rejected under current public-data/coverage constraints. Select another structural PlanOnly branch; no collect, grid, replay, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "accept_spot_perp_basis_rejection_on_current_public_probe",
        "run_structural_branch_planonly",
        "keep_collect_grid_replay_live_api_and_paper_forward_blocked"
    )
} elseif ($spotPerpBasisSelectedGate) {
    $selectedBranch = "spot_perp_basis_mean_reversion_no_funding"
    if ($spotPerpBasisAvailabilityAwaitingProbeGate) {
        $decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION"
        $reason = "spot/perp basis availability preflight found public endpoint coverage, but existing files are not backtest-ready. Await explicit confirmation for a short visible public REST probe; no actual collect, grid, replay, live, API keys, leverage or paper-forward."
        $requiresUserApproval = $true
        $requiresUserApprovalForActualCollect = $true
        $allowedImmediateWork = @(
            "await_explicit_confirmation_for_short_public_spot_perp_availability_probe",
            "keep_collect_grid_replay_live_api_and_paper_forward_blocked",
            "keep_funding_as_risk_filter_not_pnl_source"
        )
    } elseif ($spotPerpBasisAvailabilityRejectedGate) {
        $decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_RESCOPE"
        $reason = "spot/perp basis availability preflight rejected the branch under current public-data/coverage constraints. Rescope or select another structural branch; no collect, grid, replay, live, API keys, leverage or paper-forward."
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $allowedImmediateWork = @(
            "reject_or_rescope_spot_perp_basis_branch",
            "select_next_non_hft_structural_branch_planonly",
            "keep_collect_grid_replay_live_api_and_paper_forward_blocked"
        )
    } elseif ($spotPerpBasisAvailabilityPreflightReadyGate) {
        $decision = "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT"
        $reason = "spot_perp_basis_mean_reversion_no_funding scaffold is built. Next step is paired spot/perp availability preflight PlanOnly; no collect, grid, replay, live, API keys, leverage or paper-forward."
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $allowedImmediateWork = @(
            "run_spot_perp_basis_availability_preflight_planonly",
            "keep_funding_as_risk_filter_not_pnl_source",
            "do_not_start_collect_grid_replay_live_api_or_paper_forward"
        )
    } else {
        $decision = "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_RESEARCH"
        $reason = "spot_perp_basis_mean_reversion_no_funding is the selected non-HFT structural PlanOnly branch. Next step is scaffold / paired spot-perp availability preflight; no collect, grid, replay, live, API keys, leverage or paper-forward."
        $requiresUserApproval = $false
        $requiresUserApprovalForActualCollect = $false
        $allowedImmediateWork = @(
            "run_spot_perp_basis_mean_reversion_planonly",
            "define_paired_spot_perp_availability_preflight",
            "keep_funding_as_risk_filter_not_pnl_source",
            "do_not_start_collect_grid_replay_live_api_or_paper_forward"
        )
    }
} elseif ($listingEventReplayRejectedGate) {
    $decision = "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_SELECT_NEXT_BRANCH"
    $selectedBranch = "next_non_hft_structural_branch"
    $reason = "listing_event_drift_reversal fixed replay PlanOnly is rejected on current evidence: net expectancy/stress/walk-forward did not pass. Select a new non-HFT structural branch PlanOnly or design a larger independent listing-event sample; no collect, grid, replay, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "accept_listing_event_drift_reversal_rejection_on_current_sample",
        "run_structural_branch_planonly",
        "or_design_larger_independent_listing_event_sample_planonly",
        "keep_collect_grid_replay_live_api_and_paper_forward_blocked"
    )
} elseif ($listingEventReplayCandidateGate) {
    $decision = "LISTING_EVENT_REPLAY_PLANONLY_CANDIDATE_VALIDATE_INDEPENDENTLY"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "listing_event_drift_reversal is only a candidate, not accepted. Build an independent validation packet before paper-forward; no grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "build_independent_listing_event_validation_packet",
        "preserve_fixed_config_no_grid",
        "require_new_oos_walk_forward_stress_economics_before_paper_forward",
        "keep_live_api_keys_leverage_and_paper_forward_blocked"
    )
} elseif ($listingEventHistoryAvailabilityReadyGate) {
    $decision = "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event OHLCV history availability preflight is ready for a short visible public REST probe. Await explicit confirmation; no actual collect, replay, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $true
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "await_explicit_confirmation_for_public_history_availability_probe",
        "do_not_start_actual_collect_grid_replay_live_api_or_paper_forward",
        "keep_public_probe_visible_and_short",
        "retain_no_data_delisted_outcomes"
    )
} elseif ($listingEventHistoryAvailabilityAcceptedGate) {
    $decision = "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_BUILD_COLLECT_APPROVAL_PACKET"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event OHLCV history availability probe accepted enough two-venue coverage. Build the revised collect approval packet; actual collect still needs explicit confirmation."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "build_revised_visible_history_collect_approval_packet",
        "do_not_start_actual_collect_without_explicit_user_confirmation",
        "keep_replay_grid_live_api_and_paper_forward_blocked",
        "retain_no_data_delisted_outcomes"
    )
} elseif ($listingEventHistoryAvailabilityRejectedGate) {
    $decision = "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_RESAMPLE_OR_GATE_FIX_PLANONLY"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event OHLCV history availability probe rejected current sample or venue mapping. Resample/fix Gate coverage before any actual collect, replay, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "resample_listing_events_for_two_venue_history_coverage",
        "fix_gate_history_endpoint_mapping_if_needed",
        "retain_no_data_delisted_outcomes",
        "do_not_start_collect_grid_replay_live_api_or_paper_forward"
    )
} elseif ($listingEventHistoryDataQualityRejectedGate) {
    $decision = "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event OHLCV history data-quality rejected the current artifact. Next step is two-venue availability preflight before any repeated collect; no replay, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "inspect_listing_event_history_data_quality_reasons",
        "run_listing_event_history_availability_preflight_planonly",
        "keep_replay_grid_and_paper_forward_blocked",
        "preserve_survivorship_controls_and_base_fee_hurdle"
    )
} elseif ($listingEventHistoryDataQualityPendingGate) {
    $decision = "LISTING_EVENT_HISTORY_DATA_QUALITY_REQUIRED"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event OHLCV history collect completed. Next step is data-quality gate on the collected artifact before any normalizer/replay/grid work."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "run_listing_event_history_data_quality_gate",
        "keep_replay_blocked_until_history_quality_passes",
        "preserve_survivorship_controls"
    )
} elseif ($listingEventNormalizerReadyGate) {
    $decision = "LISTING_EVENT_NORMALIZER_PLANONLY_RESEARCH"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing calendar passed bias controls. Next branch step is read-only listing-event normalizer PlanOnly against the current clean WS slice; no collect, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "run_listing_event_normalizer_planonly",
        "measure_listing_event_overlap_with_clean_ws_slice",
        "block_replay_if_overlap_is_insufficient",
        "preserve_base_fee_cost_hurdle"
    )
} elseif ($listingEventHistoryCollectPreviewAwaitingApprovalGate) {
    $decision = "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event OHLCV history collect preview is ready. Await explicit user approval before implementing/running visible public-history collect; no replay, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $true
    $requiresUserApprovalForActualCollect = $true
    $allowedImmediateWork = @(
        "await_explicit_user_approval_before_visible_history_collect",
        "do_not_start_collect_grid_replay_live_api_or_paper_forward",
        "keep_replay_blocked_until_history_quality_passes",
        "preserve_survivorship_controls"
    )
} elseif ($listingEventHistoryPlanReadyGate) {
    $decision = "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_PLANONLY_RESEARCH"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "Listing-event normalizer found insufficient overlap in the current WS slice. Next step is event OHLCV history PlanOnly / visible collect preview; no actual collect, grid, replay, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "run_listing_event_history_collect_preview_planonly",
        "define_visible_history_collect_contract",
        "keep_replay_blocked_until_history_quality_passes",
        "preserve_survivorship_controls"
    )
} elseif ($crossVenueRejectedGate -or $listingEventSelectedGate) {
    $decision = "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_RESEARCH"
    $selectedBranch = "listing_event_drift_reversal"
    $reason = "cross_venue_spot_dislocation_inventory_rebalance full scan was rejected under base fees/buffers. Next branch is listing_event_drift_reversal PlanOnly only; no collect, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "build_listing_event_drift_reversal_planonly_scaffold",
        "define_listing_calendar_and_survivorship_controls",
        "define_base_fee_cost_hurdle",
        "define_oos_walk_forward_stress_economics_gates"
    )
} elseif ($crossVenueStructuralSelectedGate) {
    $decision = "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH"
    $selectedBranch = "cross_venue_spot_dislocation_inventory_rebalance"
    $reason = "cross_venue_spot_dislocation_inventory_rebalance is selected as the next non-HFT structural branch. Next work is a read-only PlanOnly detector/backtester on existing clean MEXC/Gate data; no collect, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "implement_cross_venue_dislocation_planonly_detector",
        "define_inventory_rebalance_economics",
        "define_oos_walk_forward_stress_economics_gates",
        "use_existing_clean_72h_mexc_gate_data_first"
    )
} elseif ($fundingRejectedBaseFeesGate) {
    $decision = "SELECT_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY"
    $selectedBranch = "new_non_hft_structural_branch_planonly"
    $reason = "Funding/basis carry is rejected under base/VIP0/no-volume fees. Next work is selecting a new non-HFT structural branch through PlanOnly; no collect, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "run_structural_branch_planonly",
        "define_data_requirements",
        "define_oos_walk_forward_stress_economics_gates",
        "prepare_non_starting_research_plan"
    )
} elseif ($liquiditySweepRejectedGate) {
    $decision = "NEXT_BRANCH_FUNDING_BASIS_CARRY_PLANONLY"
    $selectedBranch = "funding_basis_carry_structural_planonly"
    $reason = "Active gate rejected liquidity_sweep_reversal on train/OOS/walk-forward/stress. Select funding/basis only as a PlanOnly structural branch; no collect, grid, live, API keys, leverage or paper-forward."
    $requiresUserApproval = $false
    $requiresUserApprovalForActualCollect = $false
    $allowedImmediateWork = @(
        "run_funding_basis_planonly",
        "run_funding_cost_assumption_gate",
        "run_funding_viability_gap",
        "run_funding_candidate_watchlist",
        "run_funding_watchlist_review",
        "collect_non_secret_fee_tier_evidence_if_user_provides_it",
        "design_next_non_hft_structural_branch_if_funding_remains_unaccepted"
    )
} elseif ($fundingBlocked -and $feeTierEvidencePresent) {
    $decision = "VALIDATE_FUNDING_FEE_EVIDENCE_FIRST"
    $selectedBranch = "funding_basis_carry_fee_evidence_review"
    $reason = "Funding is blocked by current evidence, but account fee-tier evidence exists and must be mapped through the cost gate before abandoning carry."
    $allowedImmediateWork = @("run_funding_cost_assumption_gate", "rerun_funding_rank_sensitivity_only_if_gate_accepts_fee_evidence")
} elseif ($fundingBlocked -and -not $feeTierEvidencePresent) {
    $decision = "NEXT_BRANCH_SPOT_MAKER_LIQUIDITY_SWEEP_REVERSAL"
    $selectedBranch = "spot_maker_liquidity_sweep_reversal_event_quality"
    $reason = "Funding is blocked by Swarm L1/L2 and no fee-tier evidence is present. The least-refuted remaining branch is sweep/reversal, but only as a new proof pipeline on independent dense data."
    $requiresUserApproval = $false
    $allowedImmediateWork = @(
        "build_visible_ws_collect_plan",
        "define_event_quality_oos_gates",
        "add_branch_specific_acceptance_thresholds",
        "run_sweep_reversal_acceptance_gate",
        "prepare_visible_collector_wrapper_before_any_long_run",
        "ask_user_before_starting_dense_multi_day_ws_or_perp_collect"
    )
} else {
    $decision = "RUN_NEXT_GOAL_CONTROLLER"
    $reason = "No branch-specific override detected; use trading_next_goal_step.ps1."
    $allowedImmediateWork = @("run_trading_next_goal_step")
}

$selectedEvidence = [ordered]@{
    funding = Convert-RowSummary -Row $funding
    spot_maker_liquidity_sweep_reversal = Convert-RowSummary -Row $spotSweep
    sweep_reclaim_event_quality_layer = Convert-RowSummary -Row $eventQuality
    perp_microstructure = Convert-RowSummary -Row $perpSignals
    breakout_momentum = Convert-RowSummary -Row $breakout
}

if ($fundingBlocked -and $null -ne $selectedEvidence.funding) {
    $selectedEvidence.funding["branch_status_override"] = "blocked_by_swarm"
    $selectedEvidence.funding["original_scorecard_next_action"] = $selectedEvidence.funding["next_action"]
    if ($liquiditySweepRejectedGate) {
        $selectedEvidence.funding["economic_status"] = "blocked_by_swarm_and_current_cost_model_not_accepted; funding can only reopen as PlanOnly structural diagnostics."
        $selectedEvidence.funding["next_action"] = "blocked_by_swarm_do_not_run_7d_funding_collect_or_final_review; liquidity_sweep_reversal_rejected; run trading_funding_basis_planonly.ps1 and require fee-tier/economics evidence before any new collect."
    } else {
        $selectedEvidence.funding["economic_status"] = "blocked_by_swarm_and_current_evidence_failed; no funding rank/backtest/paper-forward."
        $selectedEvidence.funding["next_action"] = "blocked_by_swarm_do_not_run_7d_funding_collect_or_final_review; follow guarded WS collect planning via trading_next_goal_step.ps1."
    }
    if ($gate.PSObject.Properties.Name -contains "postprocess_block" -and $null -ne $gate.postprocess_block) {
        $selectedEvidence.funding["postprocess_block_reasons"] = @($gate.postprocess_block.readiness_reasons)
        $selectedEvidence.funding["min_rows_per_cycle"] = $gate.postprocess_block.min_rows_per_cycle
    }
}

$nextProofGates = @(
    "independent_data_manifest_final_true",
    "minimum_trades_per_config_gte_20",
    "win_rate_gte_0_60",
    "expectancy_quote_gt_0",
    "net_pnl_after_costs_gt_0",
    "profit_factor_gte_1_20",
    "max_drawdown_quote_lte_5",
    "oos_and_walk_forward_acceptance",
    "stress_acceptance",
    "maker_fill_and_adverse_selection_metrics",
    "sweep_reversal_branch_specific_acceptance_gate",
    "paper_forward_only_after_research_acceptance"
)

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_branch_selector"
    decision = $decision
    selected_branch = $selectedBranch
    reason = $reason
    requires_user_approval = $requiresUserApproval
    requires_user_approval_for_immediate_work = $requiresUserApproval
    requires_user_approval_for_actual_collect = $requiresUserApprovalForActualCollect
    funding_blocked_by_swarm = $fundingBlocked
    fee_tier_evidence_present = $feeTierEvidencePresent
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
    slow_liquidity_data_availability_ready_gate = $slowLiquidityDataAvailabilityReadyGate
    slow_liquidity_data_availability_accepted_gate = $slowLiquidityDataAvailabilityAcceptedGate
    slow_liquidity_data_availability_rejected_gate = $slowLiquidityDataAvailabilityRejectedGate
    slow_liquidity_history_data_plan_ready_gate = $slowLiquidityHistoryDataPlanReadyGate
    slow_liquidity_history_quality_accepted_gate = $slowLiquidityHistoryQualityAcceptedGate
    slow_liquidity_fixed_signal_ready_gate = $slowLiquidityFixedSignalReadyGate
    slow_liquidity_feature_normalizer_ready_gate = $slowLiquidityFeatureNormalizerReadyGate
    slow_liquidity_feature_normalizer_rejected_gate = $slowLiquidityFeatureNormalizerRejectedGate
    slow_liquidity_feature_normalizer_artifact_is_v1 = $slowLiquidityFeatureNormalizerArtifactIsV1
    slow_liquidity_new_structural_hypothesis_requires_user_approval = [bool](
        $slowLiquidityFeatureNormalizerRejectedGate -and
        $slowLiquidityFeatureNormalizerArtifactIsV1
    )
    gate_status = $gate.status
    acceptance_stage = $acceptance.stage
    research_accepted = $acceptance.accepted
    live_orders = $false
    allowed_immediate_work = $allowedImmediateWork
    blocked_work = $blockedWork
    next_proof_gates = $nextProofGates
    selected_evidence = $selectedEvidence
    artifacts = [ordered]@{
        scorecard = $scorecardPath
        branch_decision = $branchDecisionPath
        fee_tier_evidence = $feeTierEvidencePath
        funding_cost_assumption_gate = $fundingCostAssumptionGateScript
        sweep_reversal_acceptance_gate = $sweepReversalGateScript
        sweep_reversal_acceptance_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $sweepReversalGateScript"
        funding_basis_planonly = $fundingBasisPlanOnlyScript
        funding_basis_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $fundingBasisPlanOnlyScript -Json"
        structural_branch_planonly = $structuralBranchPlanOnlyScript
        structural_branch_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $structuralBranchPlanOnlyScript -Json"
        structural_branch_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $structuralBranchPlanOnlyScript -UpdateGate -Json"
        slow_liquidity_regime_planonly = $slowLiquidityPlanOnlyScript
        slow_liquidity_regime_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityPlanOnlyScript -Json"
        slow_liquidity_regime_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityPlanOnlyScript -UpdateGate -Json"
        slow_liquidity_data_availability_preflight = $slowLiquidityDataAvailabilityPreflightScript
        slow_liquidity_data_availability_preflight_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityDataAvailabilityPreflightScript -Json"
        slow_liquidity_data_availability_preflight_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityDataAvailabilityPreflightScript -UpdateGate -Json"
        slow_liquidity_history_data_plan = $slowLiquidityHistoryDataPlanScript
        slow_liquidity_history_data_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityHistoryDataPlanScript -Json"
        slow_liquidity_history_data_plan_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityHistoryDataPlanScript -UpdateGate -Json"
        slow_liquidity_fixed_signal_plan = $slowLiquidityFixedSignalPlanScript
        slow_liquidity_fixed_signal_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedSignalPlanScript -Json"
        slow_liquidity_fixed_signal_plan_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFixedSignalPlanScript -UpdateGate -Json"
        slow_liquidity_feature_normalizer = $slowLiquidityFeatureNormalizerScript
        slow_liquidity_feature_normalizer_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFeatureNormalizerScript -Json"
        slow_liquidity_feature_normalizer_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $slowLiquidityFeatureNormalizerScript -UpdateGate -Json"
        spot_perp_basis_mean_reversion_planonly = $spotPerpBasisPlanOnlyScript
        spot_perp_basis_mean_reversion_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPlanOnlyScript -Json"
        spot_perp_basis_availability_preflight = $spotPerpBasisAvailabilityPreflightScript
        spot_perp_basis_availability_preflight_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisAvailabilityPreflightScript -Json"
        spot_perp_basis_availability_preflight_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisAvailabilityPreflightScript -UpdateGate -Json"
        spot_perp_basis_public_probe = $spotPerpBasisPublicProbeScript
        spot_perp_basis_public_probe_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -UpdateGate -Json"
        spot_perp_basis_public_probe_after_confirmation_command = if ($gate.command_after_explicit_approval) { [string]$gate.command_after_explicit_approval } else { "pwsh -NoProfile -ExecutionPolicy Bypass -File $spotPerpBasisPublicProbeScript -ConfirmedPublicProbe -UpdateGate -Json" }
        listing_event_planonly = $listingEventPlanOnlyScript
        listing_event_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventPlanOnlyScript -Json"
        listing_event_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventPlanOnlyScript -UpdateGate -Json"
        listing_event_normalizer_planonly = $listingEventNormalizerPlanOnlyScript
        listing_event_normalizer_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventNormalizerPlanOnlyScript -Json"
        listing_event_normalizer_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventNormalizerPlanOnlyScript -UpdateGate -Json"
        listing_event_history_planonly = $listingEventHistoryPlanOnlyScript
        listing_event_history_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -Json"
        listing_event_history_planonly_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -UpdateGate -Json"
        listing_event_history_collect_preview = $listingEventHistoryCollectPreviewScript
        listing_event_history_collect_preview_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectPreviewScript -Json"
        listing_event_history_collect_preview_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectPreviewScript -UpdateGate -Json"
        listing_event_history_collect_approval_packet = $listingEventHistoryCollectApprovalPacketScript
        listing_event_history_collect_approval_packet_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectApprovalPacketScript -Json"
        listing_event_history_collect_visible = $listingEventHistoryCollectVisibleScript
        listing_event_history_collect_visible_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectVisibleScript -PlanOnly"
        listing_event_history_collect_visible_after_approval_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryCollectVisibleScript -ConfirmedListingHistoryCollect"
        listing_event_history_data_quality = $listingEventHistoryDataQualityScript
        listing_event_history_data_quality_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryDataQualityScript -Json"
        listing_event_history_data_quality_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryDataQualityScript -UpdateGate -Json"
        listing_event_history_recollect_plan_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryPlanOnlyScript -Json"
        listing_event_history_availability_preflight = $listingEventHistoryAvailabilityPreflightScript
        listing_event_history_availability_preflight_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryAvailabilityPreflightScript -Json"
        listing_event_history_availability_preflight_update_gate_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryAvailabilityPreflightScript -UpdateGate -Json"
        listing_event_history_availability_public_probe_after_confirmation_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventHistoryAvailabilityPreflightScript -ConfirmedPublicProbe -UpdateGate -Json"
        listing_event_replay_planonly = $listingEventReplayPlanOnlyScript
        listing_event_replay_planonly_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $listingEventReplayPlanOnlyScript -Json"
        visible_ws_collect = $visibleWsCollectScript
        visible_ws_collect_plan = $visibleWsCollectPreviewCommand
        visible_ws_collect_after_approval = $visibleWsCollectCommand
        visible_ws_collect_requires_user_approval = $visibleWsCollectRequiresUserApproval
        visible_ws_collect_command_resolution = $visibleWsCollectCommandResolution
        visible_ws_collect_plan_preview_latest = $visibleWsPlanPreviewLatest
        visible_ws_collect_preview_shortcut = $visibleWsPreviewShortcut
        visible_ws_collect_confirmed_shortcut = $visibleWsConfirmedShortcut
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
    exit 0
}

Write-Host "trading_mvp Branch Selector" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Decision: $decision"
Write-Host "Selected branch: $selectedBranch"
Write-Host "Reason: $reason"
Write-Host "Requires user approval now: $requiresUserApproval"
Write-Host ""
Write-Host "State" -ForegroundColor Yellow
Write-Host "  Gate: $($result.gate_status)"
Write-Host "  Acceptance stage: $($result.acceptance_stage)"
Write-Host "  Research accepted: $($result.research_accepted)"
Write-Host "  Funding blocked by swarm: $fundingBlocked"
Write-Host "  Fee-tier evidence present: $feeTierEvidencePresent"
Write-Host ""
Write-Host "Allowed immediate work" -ForegroundColor Yellow
foreach ($item in $allowedImmediateWork) {
    Write-Host "  - $item"
}
Write-Host ""
Write-Host "Blocked work" -ForegroundColor Yellow
foreach ($item in $blockedWork) {
    Write-Host "  - $item"
}
Write-Host ""
Write-Host "Next proof gates" -ForegroundColor Yellow
foreach ($item in $nextProofGates) {
    Write-Host "  - $item"
}
