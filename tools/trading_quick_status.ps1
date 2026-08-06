param(
    [switch]$Json,
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [string]$PlanPreviewPath = "",
    [string]$HypothesisBankPath = "",
    [string]$ContinuousProductionPolicyPath = "",
    [switch]$SkipSwarm
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$swarmStatusScript = Join-Path $repoRoot "tools\trading_swarm_status.ps1"
$startDenseWsShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"
$defaultPlanPreviewPath = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"
$legacyPlanPreviewPath = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_6h_plan_preview_latest.json"
$defaultHypothesisBankPath = Join-Path $repoRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
$defaultContinuousProductionPolicyPath = Join-Path $repoRoot "docs\plans\trading-mvp-continuous-production-policy-v1.json"

if ([string]::IsNullOrWhiteSpace($PlanPreviewPath)) {
    if (Test-Path -LiteralPath $defaultPlanPreviewPath) {
        $PlanPreviewPath = $defaultPlanPreviewPath
    } elseif (Test-Path -LiteralPath $legacyPlanPreviewPath) {
        $PlanPreviewPath = $legacyPlanPreviewPath
    } else {
        $PlanPreviewPath = $defaultPlanPreviewPath
    }
}
if ([string]::IsNullOrWhiteSpace($HypothesisBankPath)) {
    $HypothesisBankPath = $defaultHypothesisBankPath
}
if ([string]::IsNullOrWhiteSpace($ContinuousProductionPolicyPath)) {
    $ContinuousProductionPolicyPath = $defaultContinuousProductionPolicyPath
}

function Read-JsonFileIfExists {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
}

function Get-PreviewStartCommand {
    param([object]$Preview)
    if ($null -eq $Preview) {
        return ""
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Preview.command_after_explicit_approval)) {
        return [string]$Preview.command_after_explicit_approval
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Preview.recommended_command_after_explicit_approval)) {
        return [string]$Preview.recommended_command_after_explicit_approval
    }
    if ($Preview.dense_collect_plan -and -not [string]::IsNullOrWhiteSpace([string]$Preview.dense_collect_plan.recommended_command_after_explicit_approval)) {
        return [string]$Preview.dense_collect_plan.recommended_command_after_explicit_approval
    }
    return ""
}

function Get-PreviewPlanCommand {
    param([object]$Preview)
    if ($null -eq $Preview) {
        return ""
    }
    if ($Preview.dense_collect_plan -and -not [string]::IsNullOrWhiteSpace([string]$Preview.dense_collect_plan.recommended_planonly_command)) {
        return [string]$Preview.dense_collect_plan.recommended_planonly_command
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Preview.recommended_planonly_command)) {
        return [string]$Preview.recommended_planonly_command
    }
    return ""
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -GatePath $GatePath -Json | ConvertFrom-Json
$preview = Read-JsonFileIfExists -Path $PlanPreviewPath
$hypothesisBank = Read-JsonFileIfExists -Path $HypothesisBankPath
$continuousPolicy = Read-JsonFileIfExists -Path $ContinuousProductionPolicyPath

$eligibleStatuses = @(
    "BANKED_NEEDS_NEW_DATA",
    "FROZEN_PIPELINE_IMPLEMENTED_NOT_COLLECTED"
)
$eligibleDataTypes = @(
    "DENSE_WS_SEGMENTED",
    "DENSE_WS_SEGMENTED_AND_MARK_INDEX"
)
$eligibleDenseHypothesisIds = if ($hypothesisBank) {
    @(
        $hypothesisBank.hypotheses |
            Where-Object {
                $eligibleStatuses -contains [string]$_.status -and
                $eligibleDataTypes -contains [string]$_.required_data_type
            } |
            ForEach-Object { [string]$_.id }
    )
} else {
    @()
}
$previewHypothesisId = if (
    $preview -and
    $null -ne $preview.PSObject.Properties["frozen_hypothesis_id"] -and
    -not [string]::IsNullOrWhiteSpace([string]$preview.frozen_hypothesis_id)
) {
    [string]$preview.frozen_hypothesis_id
} elseif ($preview) {
    [string]$preview.selected_branch
} else {
    ""
}
$previewHypothesisEligible = (
    -not [string]::IsNullOrWhiteSpace($previewHypothesisId) -and
    $eligibleDenseHypothesisIds -contains $previewHypothesisId
)
$maxApprovedWindowRuntimeSec = if ($continuousPolicy) {
    [Math]::Max(
        [int64]$continuousPolicy.runtime.weeknight_envelope_max_runtime_sec,
        [int64]$continuousPolicy.runtime.weekend_envelope_max_runtime_sec
    )
} else {
    0
}
$previewRuntimeSec = if ($preview) { [int64][Math]::Ceiling([double]$preview.hours * 3600.0) } else { 0 }
$previewFitsApprovedWindow = (
    $previewRuntimeSec -gt 0 -and
    $maxApprovedWindowRuntimeSec -gt 0 -and
    $previewRuntimeSec -le $maxApprovedWindowRuntimeSec
)

$swarmStatus = $null
if (-not $SkipSwarm -and (Test-Path -LiteralPath $swarmStatusScript)) {
    try {
        $swarmStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $swarmStatusScript -Json | ConvertFrom-Json
    } catch {
        $swarmStatus = [pscustomobject]@{
            status = "SWARM_STATUS_ERROR"
            swarm_limited = $true
            read_error = $_.Exception.Message
        }
    }
}

$previewCommand = Get-PreviewPlanCommand -Preview $preview
$startCommand = Get-PreviewStartCommand -Preview $preview
$gateStatus = [string]$gate.status
$replayAllowed = if ($null -ne $gate.PSObject.Properties["replay_allowed"]) { [bool]$gate.replay_allowed } else { $false }
$requiresApproval = if ($null -ne $gate.PSObject.Properties["requires_explicit_user_approval_for_actual_collect"]) {
    [bool]$gate.requires_explicit_user_approval_for_actual_collect
} else {
    $true
}

$status = "CHECK_GATE"
$nextAction = "Run the guarded status/preflight flow before changing the proof pipeline."
$requiredInput = ""
$allowedActions = @("quick_status_checks")
$blockedActions = @(
    "hidden_background_long_runs",
    "live_orders",
    "api_keys",
    "leverage_or_margin",
    "replay_or_grid_on_rejected_artifact",
    "postprocess_without_matching_completed_manifest"
)

if ($gateStatus -eq "RUNNING") {
    $status = "RUNNING_STATUS_ONLY"
    $nextAction = "Do only short status/ETA checks until the active run finishes."
    $allowedActions = @("status_eta_checks_only")
} elseif ($gateStatus -eq "STOPPED_INCOMPLETE") {
    $status = "STOPPED_INCOMPLETE_VISIBLE_RESUME_REQUIRED"
    $nextAction = "Resume the same run visibly with the guarded resume path, or explicitly reject the incomplete dataset."
    $requiredInput = "visible_resume_or_reject_dataset"
    $allowedActions = @("visible_resume_current_run", "explicitly_reject_incomplete_dataset")
} elseif ($gateStatus -eq "READY_FOR_POSTPROCESS" -and -not $replayAllowed) {
    if (-not $previewHypothesisEligible) {
        $status = "STALE_DENSE_WS_PLAN_REQUIRES_NEW_HASH_BOUND_PLAN"
        $nextAction = "Do not use START72H. Build a new PlanOnly campaign from an eligible frozen hypothesis and bind its scope, deadline, output namespace, and hashes."
        $allowedActions = @("quick_status_checks", "new_hash_bound_planonly_campaign")
        $blockedActions += "legacy_START72H_shortcut"
    } elseif (-not $previewFitsApprovedWindow) {
        $status = "PLAN_RUNTIME_OUTSIDE_APPROVED_WINDOWS"
        $nextAction = "Split the candidate into independently durable hash-bound phases or shorten it to an approved rolling window before requesting launch approval."
        $allowedActions = @("quick_status_checks", "new_hash_bound_planonly_campaign")
        $blockedActions += "runtime_outside_rolling_window"
    } else {
        $status = "AWAITING_EXACT_CAMPAIGN_APPROVAL"
        $nextAction = "Prepare the exact immutable campaign packet, then request one explicit approval for that run."
        $requiredInput = "exact_campaign_approval"
        $allowedActions = @("quick_status_checks", "non_starting_plan_preview", "exact_visible_campaign_after_user_approval")
    }
} elseif ($gateStatus -eq "READY_FOR_POSTPROCESS" -and $replayAllowed) {
    $status = "READY_FOR_GUARDED_REPLAY_VALIDATION"
    $nextAction = "Run guarded postprocess/replay validation with the completed manifest and matching postprocess artifact."
    $allowedActions = @("guarded_postprocess", "guarded_replay_validation_planonly")
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_quick_status"
    safe_for_frequent_checks = $true
    would_start = $false
    status = $status
    gate_status = $gateStatus
    run_id = [string]$gate.run_id
    replay_allowed = $replayAllowed
    next_goal_decision = [string]$gate.next_goal_decision
    requires_explicit_user_approval_for_actual_collect = $requiresApproval
    required_user_input = $requiredInput
    next_action = $nextAction
    allowed_actions = $allowedActions
    blocked_actions = $blockedActions
    visible_start_shortcut = if ($previewHypothesisEligible -and $previewFitsApprovedWindow) { $startDenseWsShortcut } else { $null }
    plan_preview_path = $PlanPreviewPath
    plan_preview_present = [bool]($null -ne $preview)
    hypothesis_bank_path = $HypothesisBankPath
    continuous_production_policy_path = $ContinuousProductionPolicyPath
    eligible_dense_hypothesis_ids = @($eligibleDenseHypothesisIds)
    plan_preview = if ($preview) {
        [ordered]@{
            mode = [string]$preview.mode
            would_start = [bool]$preview.would_start
            hours = $preview.hours
            max_pairs_per_exchange = $preview.max_pairs_per_exchange
            universe_path = [string]$preview.universe_path
            selected_hypothesis_id = $previewHypothesisId
            frozen_hypothesis_eligible = $previewHypothesisEligible
            fits_any_approved_window = $previewFitsApprovedWindow
            max_approved_window_runtime_sec = $maxApprovedWindowRuntimeSec
            preview_command = $previewCommand
            command_after_explicit_approval = if ($previewHypothesisEligible -and $previewFitsApprovedWindow) { $startCommand } else { $null }
        }
    } else {
        $null
    }
    swarm_status = if ($swarmStatus) {
        [ordered]@{
            status = [string]$swarmStatus.status
            swarm_limited = [bool]$swarmStatus.swarm_limited
            independent_review_available = [bool]$swarmStatus.independent_review_available
            recommended_action = [string]$swarmStatus.recommended_action
        }
    } else {
        $null
    }
    heavy_checks_skipped = @(
        "trading_goal_status.ps1",
        "trading_edge_preflight.ps1",
        "trading_ws_collect_readiness.ps1",
        "trading_collect_approval_contract.ps1",
        "trading_ws_collect_approval_packet.ps1"
    )
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "trading_mvp quick status" -ForegroundColor Cyan
Write-Host "Status: $($result.status)"
Write-Host "Gate: $($result.gate_status)"
Write-Host "Run: $($result.run_id)"
Write-Host "Replay allowed: $($result.replay_allowed)"
Write-Host "Next: $($result.next_action)"
if (-not [string]::IsNullOrWhiteSpace($result.required_user_input)) {
    Write-Host "Required input: $($result.required_user_input)" -ForegroundColor Yellow
}
Write-Host "Visible start shortcut: $($result.visible_start_shortcut)"
if ($result.plan_preview_present) {
    Write-Host "Plan: $($result.plan_preview.hours)h, MaxPairsPerExchange=$($result.plan_preview.max_pairs_per_exchange)"
    Write-Host "Universe: $($result.plan_preview.universe_path)"
}
Write-Host "No collector/replay/grid/postprocess was started."
