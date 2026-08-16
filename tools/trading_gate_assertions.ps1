# Trading Gate Assertions & Active-Run Verification Module
# Extracted from trading_mvp/run_mvp.ps1 for modular reuse

function Get-FastEdgeGateResult {
    param(
        [switch]$OfflineWork,
        [string[]]$ReadResourcePath = @(),
        [string[]]$WriteResourcePath = @(),
        [string]$CustomGatePath = $ActiveRunGatePath
    )

    $checker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
    if (-not (Test-Path -LiteralPath $checker)) {
        throw "Active run gate checker not found: $checker"
    }
    $checkerArgs = @{
        Json = $true
    }
    if ($OfflineWork) {
        $checkerArgs.OfflineWork = $true
        $checkerArgs.ReadResourcePath = @($ReadResourcePath)
        $checkerArgs.WriteResourcePath = @($WriteResourcePath)
    }
    if ($CustomGatePath) {
        if (-not (Test-Path -LiteralPath $CustomGatePath)) {
            throw "Active run gate override not found: $CustomGatePath"
        }
        $checkerArgs.GatePath = $CustomGatePath
    }
    return (& $checker @checkerArgs | ConvertFrom-Json)
}

function Assert-BasisActionGate {
    param(
        [switch]$OfflineWork,
        [string]$CustomGatePath = $ActiveRunGatePath
    )

    $reads = @()
    $writes = @()
    if ($OfflineWork) {
        $reads += @($InputPath, $PlanPath, $ManifestPath, $QualityReportPath, $FeasibilityPath, $EvaluationPath, $ClosurePath, $ProbePlanPath, $CoinRegistryPath, $SprintReportPath, $ObservationPath, $StatePath, $LedgerPath) |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
        if ($ProbeManifestPaths) {
            $reads += @($ProbeManifestPaths -split "," | Where-Object { $_.Trim() })
        }
        $writes += @($OutputPath, $ReportOutputPath, $QualityReportPath, $StatePath, $LedgerPath, $SamplesPath, $WindowManifestPath) |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    }
    $gateResult = if ($OfflineWork) {
        Get-FastEdgeGateResult -OfflineWork -ReadResourcePath $reads -WriteResourcePath $writes -CustomGatePath $CustomGatePath
    } else {
        Get-FastEdgeGateResult -CustomGatePath $CustomGatePath
    }
    if ([string]$gateResult.status -eq "STOPPED_INCOMPLETE") {
        throw "Basis action blocked: active run is STOPPED_INCOMPLETE and must be resumed or rejected first."
    }
    if ([string]$gateResult.status -eq "RUNNING") {
        if (-not $OfflineWork) {
            throw "Basis market-data writer blocked by active run_id=$($gateResult.run_id)."
        }
        if ($null -eq $gateResult.scope_decision -or -not [bool]$gateResult.scope_decision.allowed) {
            $decision = if ($gateResult.scope_decision) { [string]$gateResult.scope_decision.decision } else { "missing_scope_decision" }
            throw "Basis offline action overlaps active run or has unknown scope: $decision"
        }
    }
}

function Assert-FastEdgeGateOpen {
    param([string]$CustomGatePath = $ActiveRunGatePath)
    $gateResult = Get-FastEdgeGateResult -CustomGatePath $CustomGatePath
    $ownedFastEdgeV2Run = (
        $Action -in @("fast-edge-v2-validate", "fast-edge-v2-evaluate") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V2_EVALUATION_RUNNING"
    )
    $ownedFastEdgeV3Run = (
        $Action -in @("fast-edge-v3-validate", "fast-edge-v3-evaluate") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V3_EVALUATION_RUNNING"
    )
    $ownedFastEdgeV4Run = (
        $Action -in @("fast-edge-v4-validate", "fast-edge-v4-evaluate") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V4_EVALUATION_RUNNING"
    )
    $ownedFastEdgeV5Run = (
        $Action -in @("fast-edge-v5-validate", "fast-edge-v5-evaluate") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V5_EVALUATION_RUNNING"
    )
    $ownedFastEdgeV6Run = (
        $Action -in @("fast-edge-v6-validate", "fast-edge-v6-evaluate") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V6_EVALUATION_RUNNING"
    )
    $ownedPitTrainFeasibilityRun = (
        $Action -in @("fast-edge-pit-input-plan", "fast-edge-pit-feasibility", "fast-edge-night-schedule-plan") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "PIT_TRAIN_FEASIBILITY_RUNNING"
    )
    $ownedPitFutilityRun = (
        $Action -in @("fast-edge-pit-futility-plan", "fast-edge-pit-futility-evaluate") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "PIT_FUTILITY_RUNNING"
    )
    $ownedPitFullEvaluationRun = (
        $Action -in @("fast-edge-pit-input-plan", "fast-edge-pit-evaluate", "fast-edge-pit-execution-probe-plan") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "PIT_FULL_EVALUATION_RUNNING"
    )
    $ownedPitExecutionProbeRun = (
        $Action -in @("fast-edge-pit-execution-probe-evaluate", "fast-edge-pit-paper-plan") -and
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_RUNNING"
    )
    if (
        [string]$gateResult.status -eq "STOPPED_INCOMPLETE" -or
        ([string]$gateResult.status -eq "RUNNING" -and -not $ownedFastEdgeV2Run -and -not $ownedFastEdgeV3Run -and -not $ownedFastEdgeV4Run -and -not $ownedFastEdgeV5Run -and -not $ownedFastEdgeV6Run -and -not $ownedPitTrainFeasibilityRun -and -not $ownedPitFutilityRun -and -not $ownedPitFullEvaluationRun -and -not $ownedPitExecutionProbeRun)
    ) {
        throw "Fast-edge action blocked by active run gate status=$($gateResult.status), run_id=$($gateResult.run_id)."
    }
}

function Assert-FastEdgeV3EvaluationAuthorized {
    param([string]$CustomGatePath = $ActiveRunGatePath)
    $gateResult = Get-FastEdgeGateResult -CustomGatePath $CustomGatePath
    $authorized = (
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V3_EVALUATION_RUNNING"
    )
    if (-not $authorized) {
        throw "Fast-edge v3 evaluation requires an owned visible gate: status=$($gateResult.status), run_id=$($gateResult.run_id), decision=$($gateResult.next_goal_decision)."
    }
}

function Assert-FastEdgeV4EvaluationAuthorized {
    param([string]$CustomGatePath = $ActiveRunGatePath)
    $gateResult = Get-FastEdgeGateResult -CustomGatePath $CustomGatePath
    $authorized = (
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V4_EVALUATION_RUNNING"
    )
    if (-not $authorized) {
        throw "Fast-edge v4 evaluation requires an owned visible gate: status=$($gateResult.status), run_id=$($gateResult.run_id), decision=$($gateResult.next_goal_decision)."
    }
}

function Assert-FastEdgeV5EvaluationAuthorized {
    param([string]$CustomGatePath = $ActiveRunGatePath)
    $gateResult = Get-FastEdgeGateResult -CustomGatePath $CustomGatePath
    $authorized = (
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V5_EVALUATION_RUNNING"
    )
    if (-not $authorized) {
        throw "Fast-edge v5 evaluation requires an owned visible gate: status=$($gateResult.status), run_id=$($gateResult.run_id), decision=$($gateResult.next_goal_decision)."
    }
}

function Assert-FastEdgeV6EvaluationAuthorized {
    param([string]$CustomGatePath = $ActiveRunGatePath)
    $gateResult = Get-FastEdgeGateResult -CustomGatePath $CustomGatePath
    $authorized = (
        $RunId -and
        [string]$gateResult.run_id -eq $RunId -and
        [string]$gateResult.status -eq "RUNNING" -and
        [string]$gateResult.next_goal_decision -eq "FAST_FIRST_V6_EVALUATION_RUNNING"
    )
    if (-not $authorized) {
        throw "Fast-edge v6 evaluation requires an owned visible gate: status=$($gateResult.status), run_id=$($gateResult.run_id), decision=$($gateResult.next_goal_decision)."
    }
}
