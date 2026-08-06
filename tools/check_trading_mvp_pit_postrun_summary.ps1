[CmdletBinding(DefaultParameterSetName = "Exact")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "Exact")]
    [string]$SchedulePlanPath,
    [Parameter(Mandatory = $true, ParameterSetName = "Exact")]
    [string]$ExpectedSchedulePlanHash,
    [Parameter(Mandatory = $true, ParameterSetName = "Exact")]
    [string]$RunId,
    [Parameter(Mandatory = $true, ParameterSetName = "Guard")]
    [string]$GuardStatePath,
    [string]$SummaryPath = "",
    [string]$ReconciliationPath = "",
    [string]$SchedulePointerPath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $jsonText = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $jsonText | ConvertFrom-Json -DateKind String
    }
    return $jsonText | ConvertFrom-Json
}

function Write-Result {
    param([Parameter(Mandatory = $true)]$Payload)

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 16
        return
    }
    Write-Host "[pit-postrun-summary] status=$($Payload.status)"
    Write-Host "[pit-postrun-summary] run_id=$($Payload.run_id)"
    Write-Host "[pit-postrun-summary] next_action=$($Payload.next_action)"
}

function Write-NotApplicable {
    param(
        [Parameter(Mandatory = $true)][string]$Reason,
        [string]$ObservedRunId = ""
    )

    Write-Result -Payload ([ordered]@{
        schema = "trading_mvp_pit_postrun_summary_disposition_v1"
        status = "NOT_APPLICABLE"
        run_id = if ($ObservedRunId) { $ObservedRunId } else { $null }
        schedule_plan_path = $null
        schedule_plan_hash = $null
        summary_path = $null
        reason = $Reason
        next_action = "follow_autopilot_guard"
        exact_postrun_allowed = $false
        exact_postrun_retry_requires_quota_above_percent = $null
        new_collector_allowed = $false
        market_rows_read = $false
        returns_read = $false
        pnl_read = $false
        oos_run = $false
    })
}

function Assert-SummaryBinding {
    param(
        [Parameter(Mandatory = $true)]$Summary,
        [Parameter(Mandatory = $true)][string]$FullPlanPath,
        [Parameter(Mandatory = $true)][string]$FullQualityLedgerPath
    )

    if (
        [string]$Summary.schema -ne "trading_mvp_pit_postrun_v1" -or
        [string]$Summary.project -ne "trading_mvp" -or
        [string]$Summary.run_id -ne $RunId -or
        [string]$Summary.schedule_plan_hash -ne $ExpectedSchedulePlanHash -or
        [System.IO.Path]::GetFullPath([string]$Summary.schedule_plan_path) -ne
        $FullPlanPath -or
        [System.IO.Path]::GetFullPath([string]$Summary.quality_ledger_path) -ne
        $FullQualityLedgerPath
    ) {
        throw "Postrun summary identity, plan, or quality-ledger binding mismatch."
    }
    [void][DateTimeOffset]::Parse(
        [string]$Summary.created_at,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
    if (
        -not [string]$Summary.decision -or
        -not [string]$Summary.next_allowed_action -or
        $Summary.returns_read -ne $false -or
        $Summary.pnl_read -ne $false -or
        $Summary.oos_run -ne $false -or
        $Summary.grid_search -ne $false -or
        $Summary.live_orders -ne $false -or
        $Summary.private_api_keys -ne $false
    ) {
        throw "Postrun summary violated its decision or data embargo contract."
    }
}

try {
    if ($PSCmdlet.ParameterSetName -eq "Guard") {
        if (-not (Test-Path -LiteralPath $GuardStatePath -PathType Leaf)) {
            throw "Guard state is missing: $GuardStatePath"
        }
        $guard = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -LiteralPath $GuardStatePath -Raw
        )
        if (
            [string]$guard.schema -ne "trading_mvp_autopilot_state_v1" -or
            [string]$guard.project -ne "trading_mvp"
        ) {
            throw "Guard state schema or project is invalid."
        }

        $guardGateStatus = [string]$guard.gate.status
        $guardRunId = [string]$guard.gate.run_id
        if ($guardGateStatus -ne "READY_FOR_POSTPROCESS") {
            Write-NotApplicable `
                -Reason "gate_not_ready_for_postprocess" `
                -ObservedRunId $guardRunId
            exit 0
        }
        if (-not $guardRunId) {
            throw "READY_FOR_POSTPROCESS guard is missing gate.run_id."
        }

        $scheduleWindow = $guard.schedule_window
        $guardPlanPath = [string]$scheduleWindow.plan_path
        $guardPlanHash = [string]$scheduleWindow.plan_hash
        if (-not $guardPlanPath -or -not $guardPlanHash) {
            Write-NotApplicable `
                -Reason "active_pit_schedule_not_available" `
                -ObservedRunId $guardRunId
            exit 0
        }
        if ($guardPlanHash -notmatch "^[0-9a-f]{64}$") {
            throw "Guard schedule plan hash is invalid."
        }
        if (-not (Test-Path -LiteralPath $guardPlanPath -PathType Leaf)) {
            throw "Guard schedule plan is missing: $guardPlanPath"
        }

        $guardPlan = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -LiteralPath $guardPlanPath -Raw
        )
        if ([string]$guardPlan.plan_hash -ne $guardPlanHash) {
            throw "Guard schedule plan hash binding mismatch."
        }
        $guardSegments = @(
            $guardPlan.segments |
                Where-Object { [string]$_.run_id -eq $guardRunId }
        )
        if ($guardSegments.Count -eq 0) {
            Write-NotApplicable `
                -Reason "gate_run_not_in_active_pit_schedule" `
                -ObservedRunId $guardRunId
            exit 0
        }
        if ($guardSegments.Count -ne 1) {
            throw (
                "Expected exactly one active schedule segment for " +
                "gate.run_id=$guardRunId, observed=$($guardSegments.Count)."
            )
        }

        $SchedulePlanPath = $guardPlanPath
        $ExpectedSchedulePlanHash = $guardPlanHash
        $RunId = $guardRunId
        if (-not $SchedulePointerPath) {
            $SchedulePointerPath = [string]$scheduleWindow.pointer_path
        }
    }

    if ($RunId -notmatch "^[A-Za-z0-9._-]+$") {
        throw "RunId contains unsupported path characters."
    }
    if ($ExpectedSchedulePlanHash -notmatch "^[0-9a-f]{64}$") {
        throw "ExpectedSchedulePlanHash must be a lowercase SHA-256 value."
    }
    if (-not (Test-Path -LiteralPath $SchedulePlanPath -PathType Leaf)) {
        throw "Schedule plan is missing: $SchedulePlanPath"
    }

    $fullPlanPath = [System.IO.Path]::GetFullPath($SchedulePlanPath)
    $plan = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $SchedulePlanPath -Raw
    )
    if ([string]$plan.plan_hash -ne $ExpectedSchedulePlanHash) {
        throw "Schedule plan hash binding mismatch."
    }
    $segments = @($plan.segments | Where-Object { [string]$_.run_id -eq $RunId })
    if ($segments.Count -ne 1) {
        throw "Expected exactly one schedule segment for RunId=$RunId, observed=$($segments.Count)."
    }
    if (-not $SummaryPath) {
        $SummaryPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.postrun.json"
    }
    if (-not $ReconciliationPath) {
        $summaryDirectory = Split-Path -Parent $SummaryPath
        $summaryName = [System.IO.Path]::GetFileNameWithoutExtension($SummaryPath)
        $ReconciliationPath = Join-Path $summaryDirectory "$summaryName.reconciliation.json"
    }
    if (-not $SchedulePointerPath) {
        $SchedulePointerPath = Join-Path $repoRoot "docs\agent-log\trading-mvp-autopilot-schedule-pointer.json"
    }
    if (-not (Test-Path -LiteralPath $SchedulePointerPath -PathType Leaf)) {
        throw "Dynamic PIT schedule pointer is missing: $SchedulePointerPath"
    }
    $pointer = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $SchedulePointerPath -Raw
    )
    if (
        [string]$pointer.schema -ne "trading_mvp_autopilot_schedule_pointer_v1" -or
        [string]$pointer.status -ne "ACTIVE" -or
        [string]$pointer.plan_hash -ne $ExpectedSchedulePlanHash -or
        [System.IO.Path]::GetFullPath([string]$pointer.plan_path) -ne
        $fullPlanPath -or
        [string]$pointer.hypothesis_id -ne [string]$plan.hypothesis.id -or
        [string]$pointer.data_type -ne [string]$plan.hypothesis.required_data_type -or
        [string]$pointer.collection_stage -ne [string]$plan.collection_stage
    ) {
        throw "Dynamic PIT schedule pointer binding mismatch."
    }
    $qualityLedgerPath = [string]$pointer.quality_ledger_path
    if (-not $qualityLedgerPath) {
        throw "Dynamic PIT schedule pointer is missing its quality ledger path."
    }
    $fullQualityLedgerPath = [System.IO.Path]::GetFullPath($qualityLedgerPath)

    $fullSummaryPath = [System.IO.Path]::GetFullPath($SummaryPath)
    $fullReconciliationPath = [System.IO.Path]::GetFullPath($ReconciliationPath)
    if (-not (Test-Path -LiteralPath $SummaryPath -PathType Leaf)) {
        if (Test-Path -LiteralPath $ReconciliationPath -PathType Leaf) {
            throw "Postrun reconciliation exists without its canonical summary."
        }
        Write-Result -Payload ([ordered]@{
            schema = "trading_mvp_pit_postrun_summary_disposition_v1"
            status = "MISSING"
            run_id = $RunId
            schedule_plan_path = $fullPlanPath
            schedule_plan_hash = $ExpectedSchedulePlanHash
            summary_path = $fullSummaryPath
            summary_sha256 = $null
            canonical_summary_path = $fullSummaryPath
            canonical_summary_sha256 = $null
            reconciliation_path = $fullReconciliationPath
            reconciliation_sha256 = $null
            decision = $null
            bound_next_allowed_action = $null
            next_action = "run_exact_postrun"
            exact_postrun_allowed = $true
            reconciliation_requires_user_approval = $false
            exact_postrun_retry_requires_quota_above_percent = $null
            new_collector_allowed = $false
            market_rows_read = $false
            returns_read = $false
            pnl_read = $false
            oos_run = $false
        })
        exit 0
    }

    $summary = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $SummaryPath -Raw
    )
    Assert-SummaryBinding `
        -Summary $summary `
        -FullPlanPath $fullPlanPath `
        -FullQualityLedgerPath $fullQualityLedgerPath
    $canonicalSummarySha256 = (
        Get-FileHash -LiteralPath $SummaryPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $effectiveSummary = $summary
    $effectiveSummaryPath = $fullSummaryPath
    $effectiveSummarySha256 = $canonicalSummarySha256
    $reconciliationSha256 = $null

    if ([string]$summary.decision -eq "PIT_POSTRUN_FAILED") {
        $supportedFailure = (
            [string]$summary.failure -eq
            "RuntimeException: PIT post-run requires final, complete, successfully completed output."
        )
        if (-not (Test-Path -LiteralPath $ReconciliationPath -PathType Leaf)) {
            Write-Result -Payload ([ordered]@{
                schema = "trading_mvp_pit_postrun_summary_disposition_v1"
                status = "RECOVERY_REQUIRED"
                run_id = $RunId
                schedule_plan_path = $fullPlanPath
                schedule_plan_hash = $ExpectedSchedulePlanHash
                quality_ledger_path = $fullQualityLedgerPath
                summary_path = $fullSummaryPath
                summary_sha256 = $canonicalSummarySha256
                canonical_summary_path = $fullSummaryPath
                canonical_summary_sha256 = $canonicalSummarySha256
                reconciliation_path = $fullReconciliationPath
                reconciliation_sha256 = $null
                decision = [string]$summary.decision
                bound_next_allowed_action = [string]$summary.next_allowed_action
                reason = [string]$summary.failure
                next_action = if ($supportedFailure) {
                    "request_exact_postrun_reconciliation_approval"
                } else {
                    "user_review_required_before_any_recovery_or_collector"
                }
                exact_postrun_allowed = $false
                reconciliation_requires_user_approval = $true
                reconciliation_supported = $supportedFailure
                exact_postrun_retry_requires_quota_above_percent = $null
                new_collector_allowed = $false
                market_rows_read = $false
                returns_read = $false
                pnl_read = $false
                oos_run = $false
            })
            exit 0
        }
        if (-not $supportedFailure) {
            throw "Postrun reconciliation is not allowed for this failure class."
        }

        $reconciled = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -LiteralPath $ReconciliationPath -Raw
        )
        Assert-SummaryBinding `
            -Summary $reconciled `
            -FullPlanPath $fullPlanPath `
            -FullQualityLedgerPath $fullQualityLedgerPath
        $binding = $reconciled.reconciliation
        if (
            -not $binding -or
            [string]$binding.schema -ne
            "trading_mvp_pit_postrun_reconciliation_v1" -or
            [System.IO.Path]::GetFullPath(
                [string]$binding.supersedes_summary_path
            ) -ne $fullSummaryPath -or
            [string]$binding.supersedes_summary_sha256 -ne
            $canonicalSummarySha256 -or
            [string]$binding.reconciliation_reason -ne
            "recover_exact_final_output_after_control_plane_readiness_mismatch"
        ) {
            throw "Postrun reconciliation binding mismatch."
        }
        if ([string]$reconciled.decision -eq "PIT_POSTRUN_FAILED") {
            throw "Postrun reconciliation cannot repeat PIT_POSTRUN_FAILED."
        }
        $reconciliationSha256 = (
            Get-FileHash -LiteralPath $ReconciliationPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $effectiveSummary = $reconciled
        $effectiveSummaryPath = $fullReconciliationPath
        $effectiveSummarySha256 = $reconciliationSha256
    } elseif (Test-Path -LiteralPath $ReconciliationPath -PathType Leaf) {
        throw "Postrun reconciliation exists for a non-failed canonical summary."
    }

    $deferredActions = @(
        "wait_for_fresh_weekly_quota_above_15_percent_then_retry_postrun",
        "run_train_feasibility_after_weekly_quota_reset",
        "refresh_horizon_after_weekly_quota_reset_then_request_exact_schedule_approval"
    )
    $deferred = (
        [string]$effectiveSummary.decision -like "PAUSED*" -or
        [string]$effectiveSummary.next_allowed_action -in $deferredActions
    )
    $status = if ($deferred) { "DEFERRED" } else { "COMPLETE" }
    $nextAction = if ($deferred) {
        "wait_for_quota_above_15_then_retry_exact_postrun"
    } else {
        "follow_bound_summary_next_allowed_action"
    }
    Write-Result -Payload ([ordered]@{
        schema = "trading_mvp_pit_postrun_summary_disposition_v1"
        status = $status
        run_id = $RunId
        schedule_plan_path = $fullPlanPath
        schedule_plan_hash = $ExpectedSchedulePlanHash
        quality_ledger_path = $fullQualityLedgerPath
        summary_path = $effectiveSummaryPath
        summary_sha256 = $effectiveSummarySha256
        canonical_summary_path = $fullSummaryPath
        canonical_summary_sha256 = $canonicalSummarySha256
        reconciliation_path = $fullReconciliationPath
        reconciliation_sha256 = $reconciliationSha256
        decision = [string]$effectiveSummary.decision
        bound_next_allowed_action = [string]$effectiveSummary.next_allowed_action
        next_action = $nextAction
        exact_postrun_allowed = $false
        reconciliation_requires_user_approval = $false
        exact_postrun_retry_requires_quota_above_percent = if ($deferred) { 15 } else { $null }
        new_collector_allowed = $false
        market_rows_read = $false
        returns_read = $false
        pnl_read = $false
        oos_run = $false
    })
    exit 0
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    Write-Result -Payload ([ordered]@{
        schema = "trading_mvp_pit_postrun_summary_disposition_v1"
        status = "INTEGRITY_CONFLICT"
        run_id = $RunId
        schedule_plan_path = $SchedulePlanPath
        schedule_plan_hash = $ExpectedSchedulePlanHash
        summary_path = $SummaryPath
        reason = $message
        next_action = "critical_stop_and_notify_once"
        exact_postrun_allowed = $false
        exact_postrun_retry_requires_quota_above_percent = $null
        new_collector_allowed = $false
        market_rows_read = $false
        returns_read = $false
        pnl_read = $false
        oos_run = $false
    })
    exit 1
}
