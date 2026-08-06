param(
    [double]$Hours = 6.0,
    [string]$Exchanges = "mexc,gateio",
    [string]$UniversePath = "",
    [int]$MaxSymbols = 300,
    [int]$MaxPairsPerExchange = 8,
    [ValidateSet("100ms","10ms")]
    [string]$UpdateInterval = "100ms",
    [string]$RunLabel = "",
    [int]$EarlyDensityCheckAfterMinutes = 60,
    [double]$EarlyDensityMinLinesPerMinute = 10.0,
    [int]$EarlyDensityMinRawLines = 600,
    [int]$EarlyDensityMinRawFiles = 1,
    [switch]$DisableEarlyDensityGuard,
    [int]$ZeroLineAbortAfterMinutes = 10,
    [switch]$DisableZeroLineAbort,
    [int]$SchemaProbeAfterMinutes = 1,
    [int]$SchemaProbeMaxLines = 20,
    [switch]$DisableSchemaProbe,
    [switch]$NoPause,
    [switch]$ConfirmedLongRun,
    [switch]$ResumeIncomplete,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

# This legacy universe belongs to a terminally rejected branch. Keep PlanOnly
# inspection available, but fail closed before any actual writer can start.
$staleRejectedUniverseNames = @("no_binance_dense_ws_sweep_20260628.csv")
$universeLeaf = if ([string]::IsNullOrWhiteSpace($UniversePath)) {
    ""
} else {
    [System.IO.Path]::GetFileName($UniversePath)
}
if ((-not $PlanOnly) -and ($staleRejectedUniverseNames -contains $universeLeaf)) {
    throw "STALE_REJECTED_WS_ROUTE_DISABLED: actual collection for '$universeLeaf' is permanently disabled. Build and approve a new hash-bound campaign PlanOnly instead."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"
$planPreviewLatest = Join-Path $runDir "ws_collect_plan_preview_latest.json"
$legacyPlanPreviewLatest = Join-Path $runDir "ws_collect_6h_plan_preview_latest.json"
$rawDir = Join-Path $repoRoot "exports\trading-mvp\raw"
$normalizedDir = Join-Path $repoRoot "exports\trading-mvp\normalized"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$runner = Join-Path $repoRoot "trading_mvp\run_mvp.ps1"
$branchSelector = Join-Path $repoRoot "tools\trading_branch_selector.ps1"
$nextGoalStep = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$edgePreflight = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$wsCollectReadiness = Join-Path $repoRoot "tools\trading_ws_collect_readiness.ps1"
$wsPostprocess = Join-Path $repoRoot "tools\run_ws_postprocess_visible.ps1"
$wsReplayValidation = Join-Path $repoRoot "tools\run_ws_replay_validation_visible.ps1"
$denseWsCollectPlanner = Join-Path $repoRoot "tools\trading_dense_ws_collect_plan.ps1"

function Test-WsRawSchema {
    param(
        [object[]]$Files,
        [int]$MaxLines = 20
    )

    $required = @("recv_ts", "exchange", "event_type", "channel", "symbol", "payload")
    $checked = 0
    foreach ($file in @($Files)) {
        if (-not $file -or -not (Test-Path -LiteralPath $file.FullName)) {
            continue
        }
        $lines = @(Get-Content -LiteralPath $file.FullName -TotalCount $MaxLines -ErrorAction SilentlyContinue)
        foreach ($line in $lines) {
            if (-not $line) {
                continue
            }
            $checked += 1
            try {
                $row = $line | ConvertFrom-Json
            } catch {
                return [pscustomobject]@{
                    ready = $true
                    ok = $false
                    reason = "invalid_json"
                    checked_lines = $checked
                    sample_path = $file.FullName
                    error = $_.Exception.Message
                }
            }
            $names = @($row.PSObject.Properties.Name)
            $missing = @($required | Where-Object { $names -notcontains $_ })
            if ($missing.Count -gt 0) {
                return [pscustomobject]@{
                    ready = $true
                    ok = $false
                    reason = "missing_required_fields"
                    checked_lines = $checked
                    sample_path = $file.FullName
                    missing_fields = $missing
                }
            }
        }
        if ($checked -ge $MaxLines) {
            break
        }
    }
    if ($checked -eq 0) {
        return [pscustomobject]@{
            ready = $false
            ok = $false
            reason = "no_raw_lines_to_probe"
            checked_lines = 0
        }
    }
    return [pscustomobject]@{
        ready = $true
        ok = $true
        reason = "schema_probe_passed"
        checked_lines = $checked
    }
}

function Get-WsCollectManifestReadiness {
    param(
        [string]$ManifestPath,
        [int]$RequestedDurationSec
    )

    if (-not $ManifestPath -or -not (Test-Path -LiteralPath $ManifestPath)) {
        return [pscustomobject]@{
            ready = $false
            reason = "manifest_missing"
            requested_duration_sec = $RequestedDurationSec
            actual_duration_sec = $null
            total_events = 0
            error_count = 0
            final = $false
            stop_condition = "manifest_missing"
        }
    }

    try {
        $manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            ready = $false
            reason = "manifest_invalid_json"
            requested_duration_sec = $RequestedDurationSec
            actual_duration_sec = $null
            total_events = 0
            error_count = 0
            final = $false
            stop_condition = "manifest_invalid_json"
            error = $_.Exception.Message
        }
    }

    $requested = if ($manifest.PSObject.Properties.Name -contains "requested_duration_sec") {
        [int]$manifest.requested_duration_sec
    } elseif ($manifest.PSObject.Properties.Name -contains "duration_sec") {
        [int]$manifest.duration_sec
    } else {
        $RequestedDurationSec
    }
    $actual = if ($manifest.PSObject.Properties.Name -contains "actual_duration_sec") {
        [double]$manifest.actual_duration_sec
    } elseif ($manifest.PSObject.Properties.Name -contains "results") {
        $durations = @($manifest.results | ForEach-Object {
            if ($_.PSObject.Properties.Name -contains "duration_sec") { [double]$_.duration_sec }
        })
        if ($durations.Count -gt 0) { ($durations | Measure-Object -Maximum).Maximum } else { 0.0 }
    } else {
        0.0
    }
    $totalEvents = if ($manifest.PSObject.Properties.Name -contains "total_events") { [int64]$manifest.total_events } else { 0 }
    $errorCount = 0
    if ($manifest.PSObject.Properties.Name -contains "errors" -and $null -ne $manifest.errors) {
        foreach ($property in $manifest.errors.PSObject.Properties) {
            if ($property.Value -is [array]) {
                $errorCount += @($property.Value).Count
            } elseif ($null -ne $property.Value) {
                $errorCount += 1
            }
        }
    }
    $final = if ($manifest.PSObject.Properties.Name -contains "final") {
        [bool]$manifest.final
    } elseif ($manifest.PSObject.Properties.Name -contains "completed") {
        [bool]$manifest.completed
    } else {
        ($requested -gt 0 -and $actual -ge ($requested * 0.99))
    }
    $stopCondition = if ($manifest.PSObject.Properties.Name -contains "stop_condition") {
        [string]$manifest.stop_condition
    } elseif ($final) {
        "duration_sec"
    } else {
        "incomplete"
    }
    $ready = ($final -and $requested -gt 0 -and $actual -ge ($requested * 0.99) -and $totalEvents -gt 0)
    $reason = if ($ready) {
        "duration_sec_completed"
    } elseif (-not $final) {
        "manifest_not_final"
    } elseif ($requested -gt 0 -and $actual -lt ($requested * 0.99)) {
        "collector_exited_before_requested_duration"
    } elseif ($totalEvents -le 0) {
        "manifest_has_no_events"
    } else {
        "not_ready"
    }

    return [pscustomobject]@{
        ready = $ready
        reason = $reason
        requested_duration_sec = $requested
        actual_duration_sec = $actual
        total_events = $totalEvents
        error_count = $errorCount
        final = $final
        stop_condition = $stopCondition
    }
}

if (-not $ConfirmedLongRun -and -not $PlanOnly) {
    throw "Explicit long-run confirmation is required. Re-run with -ConfirmedLongRun only after the user explicitly approves this visible WS collect, or use -PlanOnly to preview without starting."
}

New-Item -ItemType Directory -Force -Path $runDir, $rawDir, $normalizedDir, (Split-Path $gatePath) | Out-Null
Set-Location $repoRoot

$resumeParentGate = $null
$resumeParentStatus = $null
if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    $resumeParentStatus = [string]$gateStatus.status
    try {
        $resumeParentGate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    } catch {
        $resumeParentGate = $null
    }
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE" -and -not $ResumeIncomplete) {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume that run explicitly or reject it before starting a new WS collect."
    }
    if ($ResumeIncomplete -and $gateStatus.status -ne "STOPPED_INCOMPLETE") {
        throw "ResumeIncomplete was requested, but active run gate status is $($gateStatus.status), not STOPPED_INCOMPLETE."
    }
} elseif ($ResumeIncomplete) {
    throw "ResumeIncomplete was requested, but active run gate does not exist."
}

$selfPreflightGuard = [ordered]@{
    enabled = $true
    script = $edgePreflight
    required_status = "READY_FOR_EDGE_PROOF_STEP"
    required_check = "current_scorecard_freshness"
    action = "refuse_confirmed_long_run_before_start"
}
$readinessGuard = [ordered]@{
    enabled = $true
    script = $wsCollectReadiness
    required_status = "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION"
    required_ok = $true
    action = "refuse_confirmed_long_run_before_start"
}

if ((-not $PlanOnly) -and $ConfirmedLongRun -and -not $ResumeIncomplete) {
    if (-not (Test-Path -LiteralPath $edgePreflight)) {
        throw "Confirmed WS collect refused: trading_edge_preflight.ps1 is missing."
    }
    $preflight = & pwsh -NoProfile -ExecutionPolicy Bypass -File $edgePreflight -Json | ConvertFrom-Json
    $preflightChecks = @($preflight.checks)
    $freshnessCheck = $preflightChecks | Where-Object { $_.name -eq "current_scorecard_freshness" } | Select-Object -First 1
    if (-not [bool]$preflight.ok) {
        throw "Confirmed WS collect refused: trading_edge_preflight.ps1 returned ok=false status=$($preflight.status) fail_count=$($preflight.fail_count)."
    }
    if ([string]$preflight.status -ne "READY_FOR_EDGE_PROOF_STEP") {
        throw "Confirmed WS collect refused: preflight status is $($preflight.status), expected READY_FOR_EDGE_PROOF_STEP."
    }
    if (-not $freshnessCheck -or [string]$freshnessCheck.status -ne "pass") {
        throw "Confirmed WS collect refused: current_scorecard_freshness did not pass."
    }
    $selfPreflightGuard.preflight_status = $preflight.status
    $selfPreflightGuard.preflight_generated_at = $preflight.generated_at
    $selfPreflightGuard.current_scorecard = $preflight.current_scorecard

    if (-not (Test-Path -LiteralPath $wsCollectReadiness)) {
        throw "Confirmed WS collect refused: trading_ws_collect_readiness.ps1 is missing."
    }
    $readiness = & pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectReadiness -Hours $Hours -MaxPairsPerExchange $MaxPairsPerExchange -UniversePath $UniversePath -ResumeIncomplete:$ResumeIncomplete -Json | ConvertFrom-Json
    if (-not [bool]$readiness.ok) {
        throw "Confirmed WS collect refused: readiness verifier returned ok=false status=$($readiness.status) fail_count=$($readiness.fail_count) warn_count=$($readiness.warn_count)."
    }
    if ([string]$readiness.status -ne "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION" -and [string]$readiness.status -ne "READY_FOR_VISIBLE_WS_COLLECT_APPROVAL_PACKET") {
        throw "Confirmed WS collect refused: readiness status is $($readiness.status), expected READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION or READY_FOR_VISIBLE_WS_COLLECT_APPROVAL_PACKET."
    }
    $readinessGuard.readiness_status = $readiness.status
    $readinessGuard.readiness_generated_at = $readiness.generated_at
    $readinessGuard.readiness_output_path = $readiness.output_path
}

$durationSec = [int][Math]::Ceiling([Math]::Max(0.01, $Hours) * 3600.0)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$hoursLabel = if ([Math]::Abs($Hours - [Math]::Round($Hours)) -lt 0.0001) { "{0}h" -f [int][Math]::Round($Hours) } else { "{0}h" -f ($Hours.ToString("0.##", [System.Globalization.CultureInfo]::InvariantCulture)) }
$label = if ($RunLabel) { $RunLabel } else { "ws_collect_${hoursLabel}_sweep_visible_$stamp" }
$stdout = Join-Path $runDir ("{0}.out.log" -f $label)
$stderr = Join-Path $runDir ("{0}.err.log" -f $label)
$startedAfter = Get-Date

$branch = $null
# Plan preview must be quick and non-invasive. The next-goal script already
# captures the selected branch decision; keep the heavier standalone branch
# selector for the actual confirmed run metadata only.
if ((-not $PlanOnly) -and (Test-Path -LiteralPath $branchSelector)) {
    try {
        $branch = & pwsh -NoProfile -ExecutionPolicy Bypass -File $branchSelector -Json | ConvertFrom-Json
    } catch {
        $branch = [ordered]@{
            decision = "BRANCH_SELECTOR_FAILED"
            reason = $_.Exception.Message
        }
    }
}
$nextStep = $null
if (Test-Path -LiteralPath $nextGoalStep) {
    try {
        $nextStep = & pwsh -NoProfile -ExecutionPolicy Bypass -File $nextGoalStep -Json | ConvertFrom-Json
    } catch {
        $nextStep = [ordered]@{
            decision = "NEXT_GOAL_STEP_FAILED"
            reason = $_.Exception.Message
        }
    }
}

$branchSource = $null
if ($PlanOnly -and $null -eq $branch -and $null -ne $nextStep) {
    $planSelectedBranch = $null
    if (
        ($nextStep.PSObject.Properties.Name -contains "state") -and
        ($null -ne $nextStep.state) -and
        ($nextStep.state.PSObject.Properties.Name -contains "primary_edge_status") -and
        ([string]$nextStep.state.primary_edge_status -eq "next_branch_spot_maker_liquidity_sweep_reversal")
    ) {
        $planSelectedBranch = "spot_maker_liquidity_sweep_reversal_event_quality"
    } elseif ($nextStep.PSObject.Properties.Name -contains "decision") {
        $planSelectedBranch = [string]$nextStep.decision
    }
    $branch = [ordered]@{
        decision = $nextStep.decision
        selected_branch = $planSelectedBranch
    }
    $branchSource = "trading_next_goal_step"
} elseif ($null -ne $branch) {
    $branchSource = "trading_branch_selector"
}

$manifestPlaceholder = "<manifest_path_from_completed_ws_collect>"
$postprocessPlaceholder = "<exports\trading-mvp\backtests\ws_postprocess_*.json>"
$postprocessPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$wsPostprocess`" -ManifestPath $manifestPlaceholder -PlanOnly"
$postprocessRunCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$wsPostprocess`" -ManifestPath $manifestPlaceholder"
$replayValidationPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$wsReplayValidation`" -PostprocessPath $postprocessPlaceholder -ExpectedManifestPath $manifestPlaceholder -PlanOnly"
$replayValidationConfirmedCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$wsReplayValidation`" -PostprocessPath $postprocessPlaceholder -ExpectedManifestPath $manifestPlaceholder -ConfirmedResearchRun"
$universeCommandArg = if ($UniversePath) { " -UniversePath `"$UniversePath`"" } else { "" }
$earlyDensityGuard = [ordered]@{
    enabled = (-not [bool]$DisableEarlyDensityGuard)
    check_after_minutes = $EarlyDensityCheckAfterMinutes
    min_lines_per_minute = $EarlyDensityMinLinesPerMinute
    min_raw_lines = $EarlyDensityMinRawLines
    min_raw_files = $EarlyDensityMinRawFiles
    action = "stop_child_collector_and_mark_stopped_incomplete"
}
$zeroLineGuard = [ordered]@{
    enabled = (-not [bool]$DisableZeroLineAbort)
    abort_after_minutes = $ZeroLineAbortAfterMinutes
    min_raw_lines = 1
    action = "stop_child_collector_and_mark_stopped_incomplete"
}
$schemaProbe = [ordered]@{
    enabled = (-not [bool]$DisableSchemaProbe)
    check_after_minutes = $SchemaProbeAfterMinutes
    max_lines = $SchemaProbeMaxLines
    required_fields = @("recv_ts", "exchange", "event_type", "channel", "symbol", "payload")
    action = "stop_child_collector_and_mark_stopped_incomplete_on_invalid_raw_jsonl"
}

$argsList = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner,
    "-Action", "ws-collect",
    "-Exchanges", $Exchanges,
    "-MaxSymbols", $MaxSymbols,
    "-MaxPairsPerExchange", $MaxPairsPerExchange,
    "-DurationSec", $durationSec,
    "-UpdateInterval", $UpdateInterval
)
if ($UniversePath) {
    $argsList += @("-InputPath", $UniversePath)
}

if ($PlanOnly) {
    $denseCollectPlan = $null
    if (Test-Path -LiteralPath $denseWsCollectPlanner) {
        try {
            $denseCollectPlan = & pwsh -NoProfile -ExecutionPolicy Bypass -File $denseWsCollectPlanner -Exchanges $Exchanges -Json | ConvertFrom-Json
        } catch {
            $denseCollectPlan = [ordered]@{
                mode = "dense_ws_collect_plan"
                error = $_.Exception.Message
                would_start = $false
            }
        }
    }
    $recommendedCommandAfterApproval = if ($denseCollectPlan -and ($denseCollectPlan.PSObject.Properties.Name -contains "recommended_command_after_explicit_approval")) {
        $denseCollectPlan.recommended_command_after_explicit_approval
    } else {
        $null
    }
    $plan = [ordered]@{
        mode = "ws_collect_visible_plan"
        would_start = $false
        requires_confirmed_long_run = $true
        confirmed_long_run = [bool]$ConfirmedLongRun
        next_goal_decision = if ($nextStep) { $nextStep.decision } else { $null }
        next_goal_reason = if ($nextStep) { $nextStep.reason } else { $null }
        branch_decision = if ($branch) { $branch.decision } else { $null }
        selected_branch = if ($branch) { $branch.selected_branch } else { $null }
        branch_source = $branchSource
        resume_incomplete = [bool]$ResumeIncomplete
        resumed_from_run_id = if ($ResumeIncomplete -and $resumeParentGate) { [string]$resumeParentGate.run_id } else { $null }
        hours = $Hours
        duration_sec = $durationSec
        exchanges = $Exchanges
        universe_path = $UniversePath
        max_symbols = $MaxSymbols
        max_pairs_per_exchange = $MaxPairsPerExchange
        update_interval = $UpdateInterval
        raw_dir = $rawDir
        normalized_dir = $normalizedDir
        stdout_path = $stdout
        stderr_path = $stderr
        gate_path = $gatePath
        plan_preview_latest_path = $planPreviewLatest
        plan_preview_legacy_path = $legacyPlanPreviewLatest
        runner = $runner
        self_preflight_guard = $selfPreflightGuard
        readiness_guard = $readinessGuard
        early_density_guard = $earlyDensityGuard
        zero_line_guard = $zeroLineGuard
        schema_probe = $schemaProbe
        dense_collect_plan = $denseCollectPlan
        postprocess_plan_command_after_ready = $postprocessPlanCommand
        postprocess_command_after_ready = $postprocessRunCommand
        replay_validation_plan_after_postprocess = $replayValidationPlanCommand
        replay_validation_after_review = $replayValidationConfirmedCommand
        next_after_collect = "After the visible collect reaches READY_FOR_POSTPROCESS, run guarded ws-postprocess on the created ws_collect_*.json manifest, then run replay validation in PlanOnly with the same manifest as -ExpectedManifestPath. Actual replay/grid remains blocked until postprocess has replay_allowed=true and the user explicitly approves -ConfirmedResearchRun. Do not treat this collect as strategy acceptance."
        command_after_explicit_approval = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Hours $Hours -Exchanges `"$Exchanges`"$universeCommandArg -MaxSymbols $MaxSymbols -MaxPairsPerExchange $MaxPairsPerExchange -UpdateInterval `"$UpdateInterval`" -EarlyDensityCheckAfterMinutes $EarlyDensityCheckAfterMinutes -EarlyDensityMinLinesPerMinute $EarlyDensityMinLinesPerMinute -EarlyDensityMinRawLines $EarlyDensityMinRawLines -EarlyDensityMinRawFiles $EarlyDensityMinRawFiles -ZeroLineAbortAfterMinutes $ZeroLineAbortAfterMinutes -SchemaProbeAfterMinutes $SchemaProbeAfterMinutes -SchemaProbeMaxLines $SchemaProbeMaxLines -ConfirmedLongRun"
        recommended_command_after_explicit_approval = $recommendedCommandAfterApproval
    }
    $planJson = $plan | ConvertTo-Json -Depth 10
    if ($Hours -ge 1) {
        $planJson | Set-Content -Encoding UTF8 -LiteralPath $planPreviewLatest
        $planJson | Set-Content -Encoding UTF8 -LiteralPath $legacyPlanPreviewLatest
    }
    $planJson
    exit 0
}

$gate = [ordered]@{
    schema = "active_run_gate_v1"
    project = "trading_mvp"
    run_id = $label
    status = "RUNNING"
    created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    purpose = "Visible research-only WS collect for spot maker liquidity sweep/reversal branch; blocks next goal step until collector exits."
    blocking_rule = "While status is RUNNING, do not run postprocess, grid/search, code changes, broad analysis, or new collectors. Only status/ETA checks are allowed."
    monitor_pid = $PID
    process_ids = @($PID)
    monitor_script = $PSCommandPath
    output_path = $rawDir
    manifest_glob = (Join-Path $rawDir "ws_collect_*.json")
    duration_sec = $durationSec
    exchanges = $Exchanges
    max_symbols = $MaxSymbols
    max_pairs_per_exchange = $MaxPairsPerExchange
    universe_path = $UniversePath
    update_interval = $UpdateInterval
    self_preflight_guard = $selfPreflightGuard
    early_density_guard = $earlyDensityGuard
    zero_line_guard = $zeroLineGuard
    schema_probe = $schemaProbe
    next_goal_decision = if ($nextStep) { $nextStep.decision } else { $null }
    next_goal_reason = if ($nextStep) { $nextStep.reason } else { $null }
    branch_decision = if ($branch) { $branch.decision } else { $null }
    selected_branch = if ($branch) { $branch.selected_branch } else { $null }
    branch_source = $branchSource
    resume_incomplete = [bool]$ResumeIncomplete
    resumed_from_run_id = if ($ResumeIncomplete -and $resumeParentGate) { [string]$resumeParentGate.run_id } else { $null }
    resumed_from_status = if ($ResumeIncomplete) { $resumeParentStatus } else { $null }
    readiness_guard = $readinessGuard
    status_check_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
    postprocess_command_after_ready = $postprocessRunCommand
    replay_validation_plan_after_postprocess = $replayValidationPlanCommand
    replay_validation_after_review = $replayValidationConfirmedCommand
    next_step_after_ready = "Run guarded ws-postprocess with the completed manifest: $postprocessRunCommand. Then run replay validation PlanOnly with the same manifest: $replayValidationPlanCommand. Only after data-quality/replay_allowed=true and explicit review, run: $replayValidationConfirmedCommand. Do not treat as investment advice or accepted strategy."
}
$gate | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $gatePath

Write-Host "Starting visible WS collect"
Write-Host "Run id: $label"
Write-Host "Branch: $($gate.selected_branch)"
Write-Host "Duration sec: $durationSec ($Hours hours)"
Write-Host "Exchanges: $Exchanges; max pairs/exchange: $MaxPairsPerExchange; max symbols: $MaxSymbols"
Write-Host "Raw dir: $rawDir"
Write-Host "Stdout: $stdout"
Write-Host "Stderr: $stderr"
Write-Host "Status check: pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"

$pwshPath = (Get-Command pwsh -ErrorAction Stop).Source
$proc = Start-Process -FilePath $pwshPath -ArgumentList $argsList -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$gate.process_ids = @($PID, $proc.Id)
$gate | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $gatePath

Write-Host "Collector PID: $($proc.Id)"

$earlyDensityChecked = $false
$earlyDensityRejected = $false
$earlyDensityResult = $null
$zeroLineChecked = $false
$zeroLineRejected = $false
$zeroLineResult = $null
$schemaProbeChecked = $false
$schemaProbeRejected = $false
$schemaProbeResult = $null

while (-not $proc.HasExited) {
    try {
        $rawFiles = @(
            Get-ChildItem -LiteralPath $rawDir -Filter "ws_*.jsonl" -File -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -ge $startedAfter }
        )
        $rawLineCount = 0
        foreach ($file in $rawFiles) {
            try {
                $rawLineCount += (Get-Content -LiteralPath $file.FullName | Measure-Object -Line).Lines
            } catch {}
        }
        $latestManifest = Get-ChildItem -LiteralPath $rawDir -Filter "ws_collect_*.json" -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $startedAfter } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        $manifestText = if ($latestManifest) { $latestManifest.FullName } else { "not created yet" }
        $elapsedMinutes = [Math]::Max(0.001, ((Get-Date) - $startedAfter).TotalMinutes)
        $linesPerMinute = [Math]::Round($rawLineCount / $elapsedMinutes, 2)
        Write-Host ("[{0}] PID={1} raw_files={2} raw_lines={3} lines_per_min={4} latest_manifest={5}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id, $rawFiles.Count, $rawLineCount, $linesPerMinute, $manifestText)

        if ((-not $DisableZeroLineAbort) -and (-not $zeroLineChecked) -and ($elapsedMinutes -ge $ZeroLineAbortAfterMinutes)) {
            $zeroLineChecked = $true
            $zeroLineResult = [pscustomobject]@{
                checked_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
                elapsed_minutes = [Math]::Round($elapsedMinutes, 2)
                raw_files = $rawFiles.Count
                raw_lines = $rawLineCount
                min_raw_lines = 1
                ok = ($rawLineCount -gt 0)
            }
            Write-Host ("Zero-line guard: ok={0}; raw_files={1}; raw_lines={2}" -f $zeroLineResult.ok, $zeroLineResult.raw_files, $zeroLineResult.raw_lines)
            if (-not [bool]$zeroLineResult.ok) {
                $zeroLineRejected = $true
                Write-Host "Zero-line guard failed; stopping collector and marking dataset incomplete."
                try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { Write-Host ("Stop-Process failed: {0}" -f $_.Exception.Message) }
                break
            }
        }

        if ((-not $DisableSchemaProbe) -and (-not $schemaProbeChecked) -and ($elapsedMinutes -ge $SchemaProbeAfterMinutes) -and ($rawLineCount -gt 0)) {
            $schemaProbeResult = Test-WsRawSchema -Files $rawFiles -MaxLines $SchemaProbeMaxLines
            if ($schemaProbeResult.ready) {
                $schemaProbeChecked = $true
                Write-Host ("Schema probe: ok={0}; reason={1}; checked_lines={2}" -f $schemaProbeResult.ok, $schemaProbeResult.reason, $schemaProbeResult.checked_lines)
                if (-not [bool]$schemaProbeResult.ok) {
                    $schemaProbeRejected = $true
                    Write-Host "Schema probe failed; stopping collector and marking dataset incomplete."
                    try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { Write-Host ("Stop-Process failed: {0}" -f $_.Exception.Message) }
                    break
                }
            }
        }

        if ((-not $DisableEarlyDensityGuard) -and (-not $earlyDensityChecked) -and ($elapsedMinutes -ge $EarlyDensityCheckAfterMinutes)) {
            $earlyDensityChecked = $true
            $earlyDensityResult = [pscustomobject]@{
                checked_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
                elapsed_minutes = [Math]::Round($elapsedMinutes, 2)
                raw_files = $rawFiles.Count
                raw_lines = $rawLineCount
                lines_per_minute = $linesPerMinute
                min_raw_files = $EarlyDensityMinRawFiles
                min_raw_lines = $EarlyDensityMinRawLines
                min_lines_per_minute = $EarlyDensityMinLinesPerMinute
                ok = (($rawFiles.Count -ge $EarlyDensityMinRawFiles) -and ($rawLineCount -ge $EarlyDensityMinRawLines) -and ($linesPerMinute -ge $EarlyDensityMinLinesPerMinute))
            }
            Write-Host ("Early density guard: ok={0}; raw_files={1}; raw_lines={2}; lines_per_min={3}" -f $earlyDensityResult.ok, $earlyDensityResult.raw_files, $earlyDensityResult.raw_lines, $earlyDensityResult.lines_per_minute)
            if (-not [bool]$earlyDensityResult.ok) {
                $earlyDensityRejected = $true
                Write-Host "Early density guard failed; stopping collector and marking dataset incomplete."
                try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { Write-Host ("Stop-Process failed: {0}" -f $_.Exception.Message) }
                break
            }
        }

        if ((Test-Path -LiteralPath $stderr) -and (Get-Item -LiteralPath $stderr).Length -gt 0) {
            Write-Host "--- stderr tail ---"
            Get-Content -LiteralPath $stderr -Tail 5
            Write-Host "--- end stderr tail ---"
        }
    } catch {
        Write-Host ("[{0}] monitor error: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message)
    }
    Start-Sleep -Seconds 60
    try { $proc.Refresh() } catch {}
}

$proc.Refresh()
Write-Host "Collector exited. ExitCode=$($proc.ExitCode)"

$finalStatus = "STOPPED_INCOMPLETE"
$latestFinalManifest = Get-ChildItem -LiteralPath $rawDir -Filter "ws_collect_*.json" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -ge $startedAfter } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$manifestReadiness = Get-WsCollectManifestReadiness -ManifestPath $(if ($latestFinalManifest) { $latestFinalManifest.FullName } else { $null }) -RequestedDurationSec $durationSec
if ((-not $earlyDensityRejected) -and (-not $zeroLineRejected) -and (-not $schemaProbeRejected) -and $proc.ExitCode -eq 0 -and [bool]$manifestReadiness.ready) {
    $finalStatus = "READY_FOR_POSTPROCESS"
}

$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$gate | Add-Member -NotePropertyName "status" -NotePropertyValue $finalStatus -Force
$gate | Add-Member -NotePropertyName "updated_at" -NotePropertyValue ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")) -Force
$gate | Add-Member -NotePropertyName "process_ids" -NotePropertyValue @() -Force
$gate | Add-Member -NotePropertyName "manifest_path" -NotePropertyValue $(if ($latestFinalManifest) { $latestFinalManifest.FullName } else { $null }) -Force
$stopReason = if ($zeroLineRejected) { "zero_line_guard_failed" } elseif ($earlyDensityRejected) { "early_density_guard_failed" } elseif ($schemaProbeRejected) { "schema_probe_failed" } elseif ($finalStatus -eq "READY_FOR_POSTPROCESS") { $null } else { $manifestReadiness.reason }
$gate | Add-Member -NotePropertyName "stop_reason" -NotePropertyValue $stopReason -Force
$gate | Add-Member -NotePropertyName "requested_duration_sec" -NotePropertyValue $manifestReadiness.requested_duration_sec -Force
$gate | Add-Member -NotePropertyName "actual_duration_sec" -NotePropertyValue $manifestReadiness.actual_duration_sec -Force
$gate | Add-Member -NotePropertyName "total_events" -NotePropertyValue $manifestReadiness.total_events -Force
$gate | Add-Member -NotePropertyName "error_count" -NotePropertyValue $manifestReadiness.error_count -Force
$gate | Add-Member -NotePropertyName "final" -NotePropertyValue $manifestReadiness.final -Force
$gate | Add-Member -NotePropertyName "stop_condition" -NotePropertyValue $manifestReadiness.stop_condition -Force
$gate | Add-Member -NotePropertyName "manifest_readiness" -NotePropertyValue $manifestReadiness -Force
$gate | Add-Member -NotePropertyName "early_density_guard_result" -NotePropertyValue $earlyDensityResult -Force
$gate | Add-Member -NotePropertyName "zero_line_guard_result" -NotePropertyValue $zeroLineResult -Force
$gate | Add-Member -NotePropertyName "schema_probe_result" -NotePropertyValue $schemaProbeResult -Force
$gate | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $gatePath

if ((Test-Path -LiteralPath $stdout) -and (Get-Item -LiteralPath $stdout).Length -gt 0) {
    Write-Host "--- stdout tail ---"
    Get-Content -LiteralPath $stdout -Tail 20
}
if ((Test-Path -LiteralPath $stderr) -and (Get-Item -LiteralPath $stderr).Length -gt 0) {
    Write-Host "--- stderr tail ---"
    Get-Content -LiteralPath $stderr -Tail 20
}

if (-not $NoPause) {
    Read-Host "Press Enter to close this monitor"
}
