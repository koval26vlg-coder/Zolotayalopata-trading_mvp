param(
    [double]$Hours = 72.0,
    [int]$MaxPairsPerExchange = 16,
    [string]$UniversePath = "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv",
    [int]$MinUniverseRows = 32,
    [switch]$RefreshPlan,
    [switch]$ResumeIncomplete,
    [string]$HypothesisBankPath = "docs\research\trading_mvp_hypothesis_bank_v1.json",
    [string]$ContinuousProductionPolicyPath = "docs\plans\trading-mvp-continuous-production-policy-v1.json",
    [string]$OutputPath = "exports\trading-mvp\analysis\trading_ws_collect_readiness_current.json",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$edgePreflight = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$visibleWsCollect = Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"
$planPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"
$legacyPlanPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_6h_plan_preview_latest.json"
$previewShortcut = Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"
$confirmedShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"
$wsCollectorPy = Join-Path $repoRoot "trading_mvp\src\ws_collector.py"

function Resolve-RepoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

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

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing JSON file: $Path"
    }
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Test-TextAll {
    param(
        [string]$Path,
        [string[]]$Needles
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            ok = $false
            missing = @("file_missing")
        }
    }
    $text = Get-Content -Raw -LiteralPath $Path
    $missing = @($Needles | Where-Object { $text -notmatch [regex]::Escape($_) })
    return [ordered]@{
        ok = ($missing.Count -eq 0)
        missing = $missing
    }
}

$checks = [System.Collections.Generic.List[object]]::new()
$resolvedUniversePath = Resolve-RepoPath -Path $UniversePath
$resolvedHypothesisBankPath = Resolve-RepoPath -Path $HypothesisBankPath
$resolvedContinuousProductionPolicyPath = Resolve-RepoPath -Path $ContinuousProductionPolicyPath
$plan = $null
$gate = $null
$preflight = $null
$refreshError = $null
$eligibleDenseHypothesisIds = @()
$selectedHypothesisId = ""
$maxApprovedWindowRuntimeSec = 0

try {
    $hypothesisBank = Read-JsonFile -Path $resolvedHypothesisBankPath
    $eligibleStatuses = @(
        "BANKED_NEEDS_NEW_DATA",
        "FROZEN_PIPELINE_IMPLEMENTED_NOT_COLLECTED"
    )
    $eligibleDataTypes = @(
        "DENSE_WS_SEGMENTED",
        "DENSE_WS_SEGMENTED_AND_MARK_INDEX"
    )
    $eligibleDenseHypothesisIds = @(
        $hypothesisBank.hypotheses |
            Where-Object {
                $eligibleStatuses -contains [string]$_.status -and
                $eligibleDataTypes -contains [string]$_.required_data_type
            } |
            ForEach-Object { [string]$_.id }
    )
    if ($eligibleDenseHypothesisIds.Count -eq 0) {
        Add-Check $checks "frozen_hypothesis_catalog" "fail" "No eligible frozen dense-WS hypotheses were found in $resolvedHypothesisBankPath." "Freeze a supported hypothesis before preparing a collector campaign."
    } else {
        Add-Check $checks "frozen_hypothesis_catalog" "pass" "Eligible frozen dense-WS hypotheses: $($eligibleDenseHypothesisIds -join ', ')."
    }
} catch {
    Add-Check $checks "frozen_hypothesis_catalog" "fail" "Could not read frozen hypothesis bank: $($_.Exception.Message)" "Repair the hypothesis bank before preparing a collector campaign."
}

try {
    $continuousPolicy = Read-JsonFile -Path $resolvedContinuousProductionPolicyPath
    $maxApprovedWindowRuntimeSec = [Math]::Max(
        [int64]$continuousPolicy.runtime.weeknight_envelope_max_runtime_sec,
        [int64]$continuousPolicy.runtime.weekend_envelope_max_runtime_sec
    )
    $requestedRuntimeSec = [int64][Math]::Ceiling($Hours * 3600.0)
    if ($requestedRuntimeSec -le 0 -or $requestedRuntimeSec -gt $maxApprovedWindowRuntimeSec) {
        Add-Check $checks "campaign_window_capacity" "fail" "Requested runtime is ${requestedRuntimeSec}s; the largest approved rolling window is ${maxApprovedWindowRuntimeSec}s." "Split the work into independently durable hash-bound phases or shorten the campaign to an approved window."
    } else {
        Add-Check $checks "campaign_window_capacity" "pass" "Requested runtime ${requestedRuntimeSec}s fits the largest approved rolling window ${maxApprovedWindowRuntimeSec}s."
    }
} catch {
    Add-Check $checks "campaign_window_capacity" "fail" "Could not validate the rolling run-window policy: $($_.Exception.Message)" "Repair the continuous-production policy before preparing a collector campaign."
}

try {
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gate.status -eq "RUNNING") {
        Add-Check $checks "active_run_gate" "fail" "Gate status is RUNNING for run_id=$($gate.run_id)." "Only status/ETA checks are allowed."
    } elseif ($gate.status -eq "STOPPED_INCOMPLETE" -and -not $ResumeIncomplete) {
        Add-Check $checks "active_run_gate" "fail" "Gate status is STOPPED_INCOMPLETE for run_id=$($gate.run_id)." "Resume visibly or reject the incomplete dataset before starting a new collect."
    } else {
        Add-Check $checks "active_run_gate" "pass" "Gate status is $($gate.status); rows=$($gate.rows); errors=$($gate.errors)."
    }
} catch {
    Add-Check $checks "active_run_gate" "fail" "Could not run gate checker: $($_.Exception.Message)" "Fix active-run-gate before any collect."
}

try {
    $preflight = & pwsh -NoProfile -ExecutionPolicy Bypass -File $edgePreflight -Json | ConvertFrom-Json
    if ([bool]$preflight.ok -and [string]$preflight.status -eq "READY_FOR_EDGE_PROOF_STEP") {
        Add-Check $checks "edge_preflight" "pass" "Preflight ok=true status=$($preflight.status); fail_count=$($preflight.fail_count); warn_count=$($preflight.warn_count)."
    } else {
        Add-Check $checks "edge_preflight" "fail" "Preflight ok=$($preflight.ok) status=$($preflight.status); fail_count=$($preflight.fail_count); warn_count=$($preflight.warn_count)." "Run trading_edge_preflight.ps1 and fix failures."
    }
} catch {
    Add-Check $checks "edge_preflight" "fail" "Could not run trading_edge_preflight.ps1: $($_.Exception.Message)" "Fix preflight before any collect."
}

if ($RefreshPlan) {
    try {
        $planText = & pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleWsCollect -Hours $Hours -MaxPairsPerExchange $MaxPairsPerExchange -UniversePath $resolvedUniversePath -PlanOnly
        $plan = $planText | ConvertFrom-Json
        Add-Check $checks "plan_preview_refresh" "pass" "PlanOnly preview refreshed via start_ws_collect_visible.ps1; would_start=$($plan.would_start)."
    } catch {
        $refreshError = $_.Exception.Message
        Add-Check $checks "plan_preview_refresh" "fail" "Could not refresh PlanOnly preview: $refreshError" "Fix visible WS collect wrapper or run preview manually."
    }
}

if ($null -eq $plan) {
    try {
        $previewPath = if (Test-Path -LiteralPath $planPreviewLatest) { $planPreviewLatest } elseif (Test-Path -LiteralPath $legacyPlanPreviewLatest) { $legacyPlanPreviewLatest } else { $planPreviewLatest }
        $plan = Read-JsonFile -Path $previewPath
        Add-Check $checks "plan_preview_read" "pass" "Read visible WS plan preview: $previewPath."
    } catch {
        Add-Check $checks "plan_preview_read" "fail" "Could not read visible WS plan preview: $($_.Exception.Message)" "Run TRADING_PREVIEW_DENSE_WS.cmd or start_ws_collect_visible.ps1 -PlanOnly."
    }
}

if ($null -ne $plan) {
    $planUniverse = Resolve-RepoPath -Path ([string]$plan.universe_path)
    $expectedUniverse = Resolve-RepoPath -Path $resolvedUniversePath
    $selectedHypothesisId = if (
        $null -ne $plan.PSObject.Properties["frozen_hypothesis_id"] -and
        -not [string]::IsNullOrWhiteSpace([string]$plan.frozen_hypothesis_id)
    ) {
        [string]$plan.frozen_hypothesis_id
    } else {
        [string]$plan.selected_branch
    }
    $planChecks = @()
    if ([string]$plan.mode -ne "ws_collect_visible_plan") { $planChecks += "mode=$($plan.mode)" }
    if ([bool]$plan.would_start) { $planChecks += "would_start=true" }
    if (-not [bool]$plan.requires_confirmed_long_run) { $planChecks += "requires_confirmed_long_run=false" }
    if ([double]$plan.hours -ne [double]$Hours) { $planChecks += "hours=$($plan.hours)" }
    if ([int]$plan.max_pairs_per_exchange -ne [int]$MaxPairsPerExchange) { $planChecks += "max_pairs_per_exchange=$($plan.max_pairs_per_exchange)" }
    if ($planUniverse -ne $expectedUniverse) { $planChecks += "universe_path=$planUniverse" }
    if ([string]$plan.command_after_explicit_approval -notmatch "-ConfirmedLongRun") { $planChecks += "missing_ConfirmedLongRun" }
    if ([string]$plan.command_after_explicit_approval -match "-Hours 6(\s|$)") { $planChecks += "stale_hours_6_command" }
    if ($planChecks.Count -eq 0) {
        Add-Check $checks "plan_preview_alignment" "pass" "Plan is 72h dense WS, PlanOnly/non-starting, branch=$($plan.selected_branch), universe=$planUniverse."
    } else {
        Add-Check $checks "plan_preview_alignment" "fail" "Plan preview mismatch: $($planChecks -join '; ')." "Refresh the preview and align dense WS commands before starting."
    }

    if (
        -not [string]::IsNullOrWhiteSpace($selectedHypothesisId) -and
        ($eligibleDenseHypothesisIds -contains $selectedHypothesisId -or $selectedHypothesisId -eq "spot_maker_liquidity_sweep_reversal_event_quality")
    ) {
        Add-Check $checks "frozen_hypothesis_binding" "pass" "Plan is bound to eligible frozen hypothesis $selectedHypothesisId."
    } else {
        Add-Check $checks "frozen_hypothesis_binding" "fail" "Plan hypothesis '$selectedHypothesisId' is absent from the eligible frozen dense-WS catalog." "Build a new hash-bound PlanOnly campaign from the current hypothesis bank; do not launch this preview."
    }

    if ($plan.dense_collect_plan -and [bool]$plan.dense_collect_plan.verdict.requires_explicit_user_approval_for_actual_collect -and -not [bool]$plan.dense_collect_plan.live_orders) {
        Add-Check $checks "dense_plan_safety" "pass" "Dense plan is research-only and requires explicit user approval; selected markets=$($plan.dense_collect_plan.selected_option.total_markets)."
    } else {
        Add-Check $checks "dense_plan_safety" "fail" "Dense plan safety fields are missing or unsafe." "Regenerate dense collect plan before starting."
    }

    if ([string]$plan.postprocess_command_after_ready -match "run_ws_postprocess_visible.ps1" -and [string]$plan.replay_validation_plan_after_postprocess -match "ExpectedManifestPath") {
        Add-Check $checks "postprocess_chain" "pass" "Plan exposes guarded ws-postprocess and replay-validation with ExpectedManifestPath."
    } else {
        Add-Check $checks "postprocess_chain" "fail" "Plan does not expose the guarded postprocess/replay-validation chain." "Fix start_ws_collect_visible.ps1 plan output."
    }
}

try {
    if (-not (Test-Path -LiteralPath $resolvedUniversePath)) {
        Add-Check $checks "dense_universe" "fail" "Universe CSV is missing: $resolvedUniversePath." "Regenerate dense universe via trading_dense_ws_collect_plan.ps1."
    } else {
        $rows = @(Import-Csv -LiteralPath $resolvedUniversePath)
        $uniqueSymbols = @($rows | ForEach-Object { ([string]$_.symbol).Trim().ToUpperInvariant() } | Where-Object { $_ } | Sort-Object -Unique)
        if ($rows.Count -ge $MinUniverseRows -and $uniqueSymbols.Count -ge $MinUniverseRows) {
            Add-Check $checks "dense_universe" "pass" "Universe rows=$($rows.Count); unique_symbols=$($uniqueSymbols.Count); min_required=$MinUniverseRows."
        } else {
            Add-Check $checks "dense_universe" "fail" "Universe rows=$($rows.Count); unique_symbols=$($uniqueSymbols.Count); min_required=$MinUniverseRows." "Regenerate or expand dense universe."
        }
    }
} catch {
    Add-Check $checks "dense_universe" "fail" "Could not inspect universe CSV: $($_.Exception.Message)" "Fix universe CSV before starting."
}

$previewShortcutCheck = Test-TextAll -Path $previewShortcut -Needles @(
    "start_ws_collect_visible.ps1",
    "-Hours 72",
    "-PlanOnly",
    "no_binance_dense_ws_sweep_20260628.csv"
)
if ($previewShortcutCheck.ok) {
    Add-Check $checks "preview_shortcut" "pass" "Preview shortcut points to guarded 72h dense PlanOnly command."
} else {
    Add-Check $checks "preview_shortcut" "fail" "Preview shortcut mismatch: missing $($previewShortcutCheck.missing -join ', ')." "Fix TRADING_PREVIEW_DENSE_WS.cmd."
}

$mexcChunkingCheck = Test-TextAll -Path $wsCollectorPy -Needles @(
    "split_ws_symbols_for_connections",
    "channels_per_symbol",
    "max_symbols_per_connection",
    "chunk_index",
    "chunk_count",
    "MEXC supports up to"
)
if ($mexcChunkingCheck.ok) {
    Add-Check $checks "mexc_channel_chunking" "pass" "WS collector chunks MEXC symbols before the 30-channel connection limit, so -MaxPairsPerExchange 16 is split into safe connections."
} else {
    Add-Check $checks "mexc_channel_chunking" "fail" "WS collector may send too many MEXC channels in one connection: missing $($mexcChunkingCheck.missing -join ', ')." "Fix trading_mvp/src/ws_collector.py chunking before starting a 72h collect."
}

$confirmedShortcutCheck = Test-TextAll -Path $confirmedShortcut -Needles @(
    "START72H",
    "start_ws_collect_visible.ps1",
    "-Hours 72",
    "-MaxPairsPerExchange 16",
    "-ConfirmedLongRun",
    "no_binance_dense_ws_sweep_20260628.csv",
    "no live orders",
    "no API keys",
    "no leverage",
    "no margin"
)
if ($confirmedShortcutCheck.ok) {
    Add-Check $checks "confirmed_shortcut" "pass" "Confirmed shortcut requires START72H and uses guarded 72h dense ConfirmedLongRun command."
} else {
    Add-Check $checks "confirmed_shortcut" "fail" "Confirmed shortcut mismatch: missing $($confirmedShortcutCheck.missing -join ', ')." "Fix TRADING_START_DENSE_WS_CONFIRMED.cmd."
}

$staleFiles = @(
    (Join-Path $repoRoot "tools\trading_branch_selector.ps1"),
    (Join-Path $repoRoot "tools\trading_edge_preflight.ps1"),
    (Join-Path $repoRoot "tools\trading_goal_status.ps1"),
    (Join-Path $repoRoot "tools\trading_next_goal_step.ps1"),
    (Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"),
    (Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"),
    (Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"),
    (Join-Path $repoRoot "TRADING_START_6H_WS_CONFIRMED.cmd"),
    (Join-Path $repoRoot "TRADING_PREVIEW_6H_WS.cmd")
)
$staleMatches = @(Select-String -Path $staleFiles -SimpleMatch "-Hours 6 -ConfirmedLongRun" -ErrorAction SilentlyContinue)
if ($staleMatches.Count -eq 0) {
    Add-Check $checks "stale_6h_confirmed_route" "pass" "No active '-Hours 6 -ConfirmedLongRun' route found in WS control files."
} else {
    Add-Check $checks "stale_6h_confirmed_route" "fail" "Found stale 6h confirmed route: $($staleMatches[0].Path):$($staleMatches[0].LineNumber)." "Remove or supersede stale 6h confirmed route."
}

$failCount = @($checks | Where-Object { $_.status -eq "fail" }).Count
$warnCount = @($checks | Where-Object { $_.status -eq "warn" }).Count
$frozenBindingFailed = @($checks | Where-Object { $_.name -eq "frozen_hypothesis_binding" -and $_.status -eq "fail" }).Count -gt 0
$windowCapacityFailed = @($checks | Where-Object { $_.name -eq "campaign_window_capacity" -and $_.status -eq "fail" }).Count -gt 0
$status = if ($failCount -eq 0) {
    "READY_FOR_VISIBLE_WS_COLLECT_APPROVAL_PACKET"
} elseif ($frozenBindingFailed) {
    "STALE_DENSE_WS_PLAN_REQUIRES_NEW_HASH_BOUND_PLAN"
} elseif ($windowCapacityFailed) {
    "REQUESTED_RUNTIME_OUTSIDE_APPROVED_WINDOWS"
} else {
    "NOT_READY_FOR_VISIBLE_WS_COLLECT"
}
$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_ws_collect_readiness"
    ok = ($failCount -eq 0)
    status = $status
    fail_count = $failCount
    warn_count = $warnCount
    research_only = $true
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    requires_explicit_user_approval_for_actual_collect = $true
    hours = $Hours
    max_pairs_per_exchange = $MaxPairsPerExchange
    universe_path = $resolvedUniversePath
    selected_hypothesis_id = $selectedHypothesisId
    eligible_dense_hypothesis_ids = @($eligibleDenseHypothesisIds)
    hypothesis_bank_path = $resolvedHypothesisBankPath
    continuous_production_policy_path = $resolvedContinuousProductionPolicyPath
    max_approved_window_runtime_sec = $maxApprovedWindowRuntimeSec
    plan_preview_latest = $planPreviewLatest
    confirmed_shortcut = $confirmedShortcut
    command_after_explicit_approval = if ($plan -and $plan.command_after_explicit_approval) { [string]$plan.command_after_explicit_approval } else { $null }
    checks = @($checks)
}

if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $resolvedOutput = Resolve-RepoPath -Path $OutputPath
    $outputDir = Split-Path -Parent $resolvedOutput
    if ($outputDir -and (-not (Test-Path -LiteralPath $outputDir))) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }
    $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resolvedOutput -Encoding UTF8
    $result.output_path = $resolvedOutput
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "trading WS collect readiness: $status"
    Write-Host "ok=$($result.ok); fails=$failCount; warnings=$warnCount"
    foreach ($check in $checks) {
        Write-Host ("[{0}] {1}: {2}" -f $check.status.ToUpperInvariant(), $check.name, $check.evidence)
    }
    if ($result.ok) {
        Write-Host "Actual collect still requires explicit user approval and visible terminal:"
        Write-Host $result.command_after_explicit_approval
    }
}

if ($failCount -gt 0) {
    exit 2
}
exit 0
