param(
    [string]$EventQualityPath = "",
    [string]$EventValidationPath = "",
    [string]$PerpLsrV2GridPath = "",
    [string]$PerpGridPath = "",
    [string]$WsGridPath = "",
    [string]$BranchArtifactPath = "",
    [string]$OutputPath = "",
    [int]$MinEventCount = 1000,
    [double]$MinTargetBeforeStopRate = 0.60,
    [double]$MaxFalseSweepRate = 0.50,
    [int]$MinTrades = 20,
    [double]$MinWinRate = 0.60,
    [double]$MinExpectancyQuote = 0.0,
    [double]$MinNetPnlQuote = 0.0,
    [double]$MinProfitFactor = 1.20,
    [double]$MaxDrawdownQuote = 5.0,
    [switch]$RequireAccepted,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"

if (-not $EventQualityPath) {
    $EventQualityPath = Join-Path $repoRoot "exports\trading-mvp\backtests\event_quality_6h_duration_20260614_181422.json"
}
if (-not $EventValidationPath) {
    $EventValidationPath = Join-Path $repoRoot "exports\trading-mvp\backtests\event_validation_6h_duration_20260614_181422.json"
}
if (-not $PerpLsrV2GridPath) {
    $PerpLsrV2GridPath = Join-Path $repoRoot "exports\trading-mvp\backtests\perp_grid_lsr_v2_gate_hype_short_maker_cooldown10_6h_duration_20260614_181422.json"
}
if (-not $PerpGridPath) {
    $PerpGridPath = Join-Path $repoRoot "exports\trading-mvp\backtests\perp_grid_search_6h_duration_20260614_181422.json"
}
if (-not $WsGridPath) {
    $WsGridPath = Join-Path $repoRoot "exports\trading-mvp\backtests\ws_grid_search_three_signals_maker_quality_6h_20260609_optimized.json"
}
if (-not $BranchArtifactPath) {
    $BranchArtifactPath = Join-Path $repoRoot "exports\trading-mvp\analysis\spot_maker_sweep_reversal_next_branch_20260627.json"
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

function Add-Reason {
    param(
        [System.Collections.Generic.List[string]]$Reasons,
        [string]$Reason
    )
    if (-not $Reasons.Contains($Reason)) {
        $Reasons.Add($Reason) | Out-Null
    }
}

function Get-PropValue {
    param(
        $Object,
        [string]$Name,
        $Default = $null
    )
    if ($null -eq $Object) {
        return $Default
    }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) {
        return $Default
    }
    return $prop.Value
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

function Read-JsonIfExists {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Get-SignalCandidate {
    param(
        $Artifact,
        [string]$ArtifactPath,
        [string[]]$SignalNames
    )
    if ($null -eq $Artifact) {
        return [ordered]@{
            present = $false
            path = $ArtifactPath
            signal_type = $null
            metrics = $null
            eligible = $false
            eligibility_reasons = @("artifact_missing")
        }
    }

    foreach ($signalName in $SignalNames) {
        $best = Get-PropValue (Get-PropValue $Artifact "best_by_signal_type") $signalName
        if ($null -ne $best) {
            return [ordered]@{
                present = $true
                path = $ArtifactPath
                signal_type = $signalName
                metrics = Get-PropValue $best "metrics"
                eligible = [bool](Get-PropValue $best "eligible" $false)
                eligibility_reasons = @(Get-PropValue $best "eligibility_reasons" @())
            }
        }
    }

    $topResults = @(Get-PropValue $Artifact "top_results" @())
    foreach ($result in $topResults) {
        $strategy = Get-PropValue $result "strategy_config"
        $signalType = [string](Get-PropValue $strategy "signal_type")
        if ($SignalNames -contains $signalType) {
            return [ordered]@{
                present = $true
                path = $ArtifactPath
                signal_type = $signalType
                metrics = Get-PropValue $result "metrics"
                eligible = [bool](Get-PropValue $result "eligible" $false)
                eligibility_reasons = @(Get-PropValue $result "eligibility_reasons" @())
            }
        }
    }

    return [ordered]@{
        present = $true
        path = $ArtifactPath
        signal_type = $null
        metrics = $null
        eligible = $false
        eligibility_reasons = @("signal_missing")
    }
}

function Add-MetricChecks {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Prefix,
        $Candidate,
        [int]$MinTrades,
        [double]$MinWinRate,
        [double]$MinExpectancyQuote,
        [double]$MinNetPnlQuote,
        [double]$MinProfitFactor,
        [double]$MaxDrawdownQuote
    )

    $metrics = $Candidate.metrics
    if ($null -eq $metrics) {
        Add-Check $Checks "${Prefix}_metrics_present" "fail" "No metrics found for signal=$($Candidate.signal_type) in $($Candidate.path)." "Regenerate replay/grid artifact before evaluating this branch."
        return
    }

    $trades = To-NullableDouble (Get-PropValue $metrics "total_trades")
    $winRate = To-NullableDouble (Get-PropValue $metrics "win_rate")
    $expectancy = To-NullableDouble (Get-PropValue $metrics "expectancy_quote")
    $netPnl = To-NullableDouble (Get-PropValue $metrics "net_pnl_quote")
    $profitFactor = To-NullableDouble (Get-PropValue $metrics "profit_factor")
    $drawdown = To-NullableDouble (Get-PropValue $metrics "max_drawdown_quote")
    $drawdownAbs = if ($null -eq $drawdown) { $null } else { [math]::Abs($drawdown) }

    if ($null -ne $trades -and $trades -ge $MinTrades) {
        Add-Check $Checks "${Prefix}_min_trades" "pass" "trades=$trades >= $MinTrades."
    } else {
        Add-Check $Checks "${Prefix}_min_trades" "fail" "trades=$trades < $MinTrades." "Do not accept this branch on a thin sample."
    }

    if ($null -ne $winRate -and $winRate -ge $MinWinRate) {
        Add-Check $Checks "${Prefix}_min_win_rate" "pass" "win_rate=$winRate >= $MinWinRate."
    } else {
        Add-Check $Checks "${Prefix}_min_win_rate" "fail" "win_rate=$winRate < $MinWinRate." "Winrate does not pass the declared floor."
    }

    if ($null -ne $expectancy -and $expectancy -gt $MinExpectancyQuote) {
        Add-Check $Checks "${Prefix}_expectancy" "pass" "expectancy_quote=$expectancy > $MinExpectancyQuote."
    } else {
        Add-Check $Checks "${Prefix}_expectancy" "fail" "expectancy_quote=$expectancy <= $MinExpectancyQuote." "Positive expectancy after execution assumptions is required."
    }

    if ($null -ne $netPnl -and $netPnl -gt $MinNetPnlQuote) {
        Add-Check $Checks "${Prefix}_net_pnl" "pass" "net_pnl_quote=$netPnl > $MinNetPnlQuote."
    } else {
        Add-Check $Checks "${Prefix}_net_pnl" "fail" "net_pnl_quote=$netPnl <= $MinNetPnlQuote." "Net PnL after costs must be positive."
    }

    if ($null -ne $profitFactor -and $profitFactor -ge $MinProfitFactor) {
        Add-Check $Checks "${Prefix}_profit_factor" "pass" "profit_factor=$profitFactor >= $MinProfitFactor."
    } else {
        Add-Check $Checks "${Prefix}_profit_factor" "fail" "profit_factor=$profitFactor < $MinProfitFactor." "Profit factor does not pass the declared floor."
    }

    if ($null -ne $drawdownAbs -and $drawdownAbs -le $MaxDrawdownQuote) {
        Add-Check $Checks "${Prefix}_drawdown" "pass" "abs(max_drawdown_quote)=$drawdownAbs <= $MaxDrawdownQuote."
    } else {
        Add-Check $Checks "${Prefix}_drawdown" "fail" "abs(max_drawdown_quote)=$drawdownAbs > $MaxDrawdownQuote." "Drawdown exceeds the declared cap or is missing."
    }
}

$checks = [System.Collections.Generic.List[object]]::new()
$reasons = [System.Collections.Generic.List[string]]::new()

$gate = $null
try {
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ([string]$gate.status -eq "RUNNING") {
        Add-Check $checks "active_run_gate" "fail" "Gate is RUNNING for run_id=$($gate.run_id)." "Only status/ETA checks are allowed until the run finishes."
    } elseif ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
        Add-Check $checks "active_run_gate" "fail" "Gate is STOPPED_INCOMPLETE for run_id=$($gate.run_id)." "Resume visibly or declare the dataset incomplete."
    } else {
        Add-Check $checks "active_run_gate" "pass" "Gate is $($gate.status); no active long run blocks this read-only gate."
    }
} catch {
    Add-Check $checks "active_run_gate" "fail" "Gate checker failed: $($_.Exception.Message)" "Fix the active-run gate before continuing."
}

$branchArtifact = Read-JsonIfExists -Path $BranchArtifactPath
if ($null -eq $branchArtifact) {
    Add-Check $checks "branch_artifact_present" "fail" "Branch artifact is missing: $BranchArtifactPath." "Run tools/trading_branch_selector.ps1 before branch acceptance."
} else {
    Add-Check $checks "branch_artifact_present" "pass" "Branch artifact present: $BranchArtifactPath."
    $selectedBranch = [string](Get-PropValue $branchArtifact "selected_branch")
    if ($selectedBranch -eq "spot_maker_liquidity_sweep_reversal_event_quality") {
        Add-Check $checks "branch_selected" "pass" "selected_branch=$selectedBranch."
    } else {
        Add-Check $checks "branch_selected" "fail" "selected_branch=$selectedBranch." "This gate only applies to spot_maker_liquidity_sweep_reversal_event_quality."
    }
    if (-not [bool](Get-PropValue $branchArtifact "accepted_strategy" $false)) {
        Add-Check $checks "branch_not_preaccepted" "pass" "accepted_strategy=false in branch artifact."
    } else {
        Add-Check $checks "branch_not_preaccepted" "fail" "accepted_strategy=true in branch artifact." "Do not pre-accept this branch before proof gates pass."
    }
}

$eventQuality = Read-JsonIfExists -Path $EventQualityPath
$eventSummary = $null
if ($null -eq $eventQuality) {
    Add-Check $checks "event_quality_artifact_present" "fail" "Event-quality artifact is missing: $EventQualityPath." "Generate event-quality diagnostics before evaluating the branch."
} else {
    Add-Check $checks "event_quality_artifact_present" "pass" "Event-quality artifact present: $EventQualityPath."
    $eventSummary = Get-PropValue $eventQuality "summary"
    $totalSweeps = To-NullableDouble (Get-PropValue $eventSummary "total_sweeps")
    $targetBeforeStopRate = To-NullableDouble (Get-PropValue $eventSummary "target_before_stop_rate")
    $falseSweepRate = To-NullableDouble (Get-PropValue $eventSummary "false_sweep_rate")
    $avgFavorable = To-NullableDouble (Get-PropValue $eventSummary "avg_favorable_excursion_bps")
    $avgAdverse = To-NullableDouble (Get-PropValue $eventSummary "avg_adverse_excursion_bps")
    $avgAdverseAbs = if ($null -eq $avgAdverse) { $null } else { [math]::Abs($avgAdverse) }

    if ($null -ne $totalSweeps -and $totalSweeps -ge $MinEventCount) {
        Add-Check $checks "event_min_count" "pass" "total_sweeps=$totalSweeps >= $MinEventCount."
    } else {
        Add-Check $checks "event_min_count" "fail" "total_sweeps=$totalSweeps < $MinEventCount." "Collect independent dense data before accepting event diagnostics."
    }

    if ($null -ne $targetBeforeStopRate -and $targetBeforeStopRate -ge $MinTargetBeforeStopRate) {
        Add-Check $checks "event_target_before_stop_rate" "pass" "target_before_stop_rate=$targetBeforeStopRate >= $MinTargetBeforeStopRate."
    } else {
        Add-Check $checks "event_target_before_stop_rate" "fail" "target_before_stop_rate=$targetBeforeStopRate < $MinTargetBeforeStopRate." "Diagnostic event layer does not show sufficient target-before-stop quality."
    }

    if ($null -ne $falseSweepRate -and $falseSweepRate -le $MaxFalseSweepRate) {
        Add-Check $checks "event_false_sweep_rate" "pass" "false_sweep_rate=$falseSweepRate <= $MaxFalseSweepRate."
    } else {
        Add-Check $checks "event_false_sweep_rate" "fail" "false_sweep_rate=$falseSweepRate > $MaxFalseSweepRate." "Too many events are false/low-quality sweeps."
    }

    if ($null -ne $avgFavorable -and $null -ne $avgAdverseAbs -and $avgFavorable -gt $avgAdverseAbs) {
        Add-Check $checks "event_favorable_vs_adverse_excursion" "pass" "avg_favorable=$avgFavorable bps > abs(avg_adverse)=$avgAdverseAbs bps."
    } else {
        Add-Check $checks "event_favorable_vs_adverse_excursion" "fail" "avg_favorable=$avgFavorable bps, abs(avg_adverse)=$avgAdverseAbs bps." "Adverse excursion is not better than favorable excursion."
    }
}

$eventValidation = Read-JsonIfExists -Path $EventValidationPath
if ($null -eq $eventValidation) {
    Add-Check $checks "event_validation_artifact_present" "fail" "Event-validation artifact is missing: $EventValidationPath." "Run event-validation-report before evaluating OOS/walk-forward/stress acceptance."
    Add-Check $checks "oos_acceptance" "fail" "OOS validation result is missing." "Must pass before research acceptance or paper-forward."
    Add-Check $checks "walk_forward_acceptance" "fail" "Walk-forward validation result is missing." "Must pass before research acceptance or paper-forward."
    Add-Check $checks "stress_acceptance" "fail" "Stress validation result is missing." "Must pass before research acceptance or paper-forward."
} else {
    Add-Check $checks "event_validation_artifact_present" "pass" "Event-validation artifact present: $EventValidationPath."
    $validationMode = [string](Get-PropValue $eventValidation "mode")
    if ($validationMode -eq "event_validation_report") {
        Add-Check $checks "event_validation_mode" "pass" "mode=$validationMode."
    } else {
        Add-Check $checks "event_validation_mode" "fail" "mode=$validationMode." "Regenerate with event-validation-report."
    }

    $validationAccepted = [bool](Get-PropValue $eventValidation "accepted" $false)
    $validationReasons = @(Get-PropValue $eventValidation "rejection_reasons" @())
    if ($validationAccepted) {
        Add-Check $checks "event_validation_accepted" "pass" "accepted=true."
    } else {
        Add-Check $checks "event_validation_accepted" "fail" "accepted=false; reasons=$($validationReasons -join ',')." "Do not accept this branch until validation gates pass."
    }

    $oos = Get-PropValue $eventValidation "oos"
    $oosAccepted = [bool](Get-PropValue $oos "accepted" $false)
    $oosSummary = Get-PropValue $oos "summary"
    $oosSelected = To-NullableDouble (Get-PropValue $oos "selected_events")
    $oosRate = To-NullableDouble (Get-PropValue $oosSummary "target_before_stop_rate")
    $oosFalse = To-NullableDouble (Get-PropValue $oosSummary "false_sweep_rate")
    if ($oosAccepted) {
        Add-Check $checks "oos_acceptance" "pass" "selected_events=$oosSelected; target_before_stop_rate=$oosRate; false_sweep_rate=$oosFalse."
    } else {
        Add-Check $checks "oos_acceptance" "fail" "selected_events=$oosSelected; target_before_stop_rate=$oosRate; false_sweep_rate=$oosFalse." "OOS slice must pass declared thresholds."
    }

    $walk = Get-PropValue $eventValidation "walk_forward"
    $walkAccepted = [bool](Get-PropValue $walk "accepted" $false)
    $walkAcceptedWindows = To-NullableDouble (Get-PropValue $walk "accepted_windows")
    $walkRatio = To-NullableDouble (Get-PropValue $walk "accepted_ratio")
    $walkWindows = @((Get-PropValue $walk "windows" @())).Count
    if ($walkAccepted) {
        Add-Check $checks "walk_forward_acceptance" "pass" "accepted_windows=$walkAcceptedWindows/$walkWindows; accepted_ratio=$walkRatio."
    } else {
        Add-Check $checks "walk_forward_acceptance" "fail" "accepted_windows=$walkAcceptedWindows/$walkWindows; accepted_ratio=$walkRatio." "Walk-forward stability must pass declared thresholds."
    }

    $stress = Get-PropValue $eventValidation "stress"
    $stressAccepted = [bool](Get-PropValue $stress "accepted" $false)
    $stressSummary = Get-PropValue $stress "summary"
    $stressEvents = To-NullableDouble (Get-PropValue $stress "events_analyzed")
    $stressRate = To-NullableDouble (Get-PropValue $stressSummary "target_before_stop_rate")
    $stressFalse = To-NullableDouble (Get-PropValue $stressSummary "false_sweep_rate")
    if ($stressAccepted) {
        Add-Check $checks "stress_acceptance" "pass" "events=$stressEvents; target_before_stop_rate=$stressRate; false_sweep_rate=$stressFalse."
    } else {
        Add-Check $checks "stress_acceptance" "fail" "events=$stressEvents; target_before_stop_rate=$stressRate; false_sweep_rate=$stressFalse." "Stress-adjusted validation must pass declared thresholds."
    }
}

$perpLsrV2 = Read-JsonIfExists -Path $PerpLsrV2GridPath
$perpGrid = Read-JsonIfExists -Path $PerpGridPath
$wsGrid = Read-JsonIfExists -Path $WsGridPath

$candidateV2 = Get-SignalCandidate -Artifact $perpLsrV2 -ArtifactPath $PerpLsrV2GridPath -SignalNames @("liquidity_sweep_reversal_v2")
$candidatePerp = Get-SignalCandidate -Artifact $perpGrid -ArtifactPath $PerpGridPath -SignalNames @("liquidity_sweep_reversal", "liquidity_sweep_reversal_v2")
$candidateWs = Get-SignalCandidate -Artifact $wsGrid -ArtifactPath $WsGridPath -SignalNames @("liquidity_sweep_reversal", "liquidity_sweep_reversal_v2")

Add-MetricChecks $checks "execution_v2" $candidateV2 $MinTrades $MinWinRate $MinExpectancyQuote $MinNetPnlQuote $MinProfitFactor $MaxDrawdownQuote
Add-MetricChecks $checks "execution_perp_grid" $candidatePerp $MinTrades $MinWinRate $MinExpectancyQuote $MinNetPnlQuote $MinProfitFactor $MaxDrawdownQuote
Add-MetricChecks $checks "execution_ws_grid" $candidateWs $MinTrades $MinWinRate $MinExpectancyQuote $MinNetPnlQuote $MinProfitFactor $MaxDrawdownQuote

$failChecks = @($checks | Where-Object { $_.status -eq "fail" })
$warnChecks = @($checks | Where-Object { $_.status -eq "warn" })
foreach ($check in $failChecks) {
    Add-Reason $reasons $check.name
}

$accepted = ($failChecks.Count -eq 0)
$stage = if ($accepted) { "research_accepted_paper_forward_still_blocked" } else { "research_only_branch_gate_failed" }
$decision = if ($accepted) { "SWEEP_REVERSAL_RESEARCH_ACCEPTED_PAPER_FORWARD_REQUIRED" } else { "SWEEP_REVERSAL_RESEARCH_NOT_ACCEPTED_NEEDS_INDEPENDENT_DATA" }
$nextAction = if ($accepted) {
    "Freeze config and run a separate visible paper-forward plan. Live remains blocked."
} else {
    "Do not paper/live. Define OOS/walk-forward/stress gates and use only a visible user-approved independent dense WS/perp collect before replay."
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "sweep_reversal_acceptance_gate"
    branch = "spot_maker_liquidity_sweep_reversal_event_quality"
    accepted = $accepted
    stage = $stage
    decision = $decision
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    paper_forward_allowed = $false
    reasons = @($reasons)
    fail_count = $failChecks.Count
    warn_count = $warnChecks.Count
    thresholds = [ordered]@{
        min_event_count = $MinEventCount
        min_target_before_stop_rate = $MinTargetBeforeStopRate
        max_false_sweep_rate = $MaxFalseSweepRate
        min_trades = $MinTrades
        min_win_rate = $MinWinRate
        min_expectancy_quote = $MinExpectancyQuote
        min_net_pnl_quote = $MinNetPnlQuote
        min_profit_factor = $MinProfitFactor
        max_drawdown_quote_abs = $MaxDrawdownQuote
    }
    event_quality = [ordered]@{
        path = $EventQualityPath
        present = ($null -ne $eventQuality)
        summary = $eventSummary
    }
    event_validation = [ordered]@{
        path = $EventValidationPath
        present = ($null -ne $eventValidation)
        accepted = if ($null -ne $eventValidation) { [bool](Get-PropValue $eventValidation "accepted" $false) } else { $false }
        rejection_reasons = if ($null -ne $eventValidation) { @(Get-PropValue $eventValidation "rejection_reasons" @()) } else { @("artifact_missing") }
    }
    execution_candidates = [ordered]@{
        liquidity_sweep_reversal_v2 = $candidateV2
        perp_grid_liquidity_sweep_reversal = $candidatePerp
        ws_grid_liquidity_sweep_reversal = $candidateWs
    }
    checks = @($checks)
    blocked_work = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward_without_research_acceptance",
        "hidden_background_long_runs",
        "tuning_old_thin_sample",
        "new_channel_or_p2p_content_analysis"
    )
    next_action = $nextAction
}

if ($OutputPath) {
    $outputFullPath = $OutputPath
    if (-not [System.IO.Path]::IsPathRooted($outputFullPath)) {
        $outputFullPath = Join-Path $repoRoot $outputFullPath
    }
    $outputDir = Split-Path -Parent $outputFullPath
    if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $outputFullPath -Encoding UTF8
    $result["output_path"] = $outputFullPath
}

if ($Json) {
    $result | ConvertTo-Json -Depth 12
} else {
    Write-Host "trading_mvp Sweep/Reversal Acceptance Gate" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Decision: $decision"
    Write-Host "Accepted: $accepted"
    Write-Host "Fail checks: $($failChecks.Count); Warnings: $($warnChecks.Count)"
    Write-Host ""
    foreach ($check in $checks) {
        $prefix = if ($check.status -eq "pass") { "[PASS]" } elseif ($check.status -eq "warn") { "[WARN]" } else { "[FAIL]" }
        Write-Host "$prefix $($check.name): $($check.evidence)"
        if ($check.action) {
            Write-Host "       Action: $($check.action)"
        }
    }
    Write-Host ""
    Write-Host "Next action:" -ForegroundColor Yellow
    Write-Host "  $nextAction"
}

if ($RequireAccepted -and -not $accepted) {
    exit 2
}
exit 0
