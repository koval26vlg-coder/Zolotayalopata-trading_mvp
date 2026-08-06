[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SchedulePlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedSchedulePlanHash,
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$QualityLedgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl",
    [string]$ApprovalRecordRoot = "",
    [string]$SchedulePointerPath = "",
    [string]$CriticalCheckpointPath = "",
    [string]$QualityReportRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\pit-quality",
    [string]$FeasibilityArtifactRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\pit-train-feasibility",
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 1800,
    [switch]$PlanOnly,
    [switch]$ReconcileFailedSummary
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$planCli = Join-Path $repoRoot "trading_mvp\src\night_schedule_plan.py"
$qualityDryRunCli = Join-Path $repoRoot "trading_mvp\src\night_schedule_quality_dry_run.py"
$qualityCli = Join-Path $repoRoot "trading_mvp\src\night_schedule_quality.py"
$autopilotGuard = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$feasibilityTool = Join-Path $repoRoot "tools\run_pit_train_feasibility_visible.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$canonicalSummaryPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.postrun.json"
$reconciliationSummaryPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.postrun.reconciliation.json"
$reconciliationResolutionPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.postrun.reconciliation-resolution.json"
$summaryPath = $canonicalSummaryPath
$script:reconciliationBinding = $null

if (-not $ApprovalRecordRoot) {
    $ApprovalRecordRoot = Join-Path $repoRoot "docs\agent-log\night-schedule-approvals"
}
if (-not $SchedulePointerPath) {
    $SchedulePointerPath = Join-Path $repoRoot "docs\agent-log\trading-mvp-autopilot-schedule-pointer.json"
}
if (-not $CriticalCheckpointPath) {
    $CriticalCheckpointPath = Join-Path $repoRoot "docs\agent-log\trading-mvp-critical-checkpoint.json"
}

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $jsonText = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $jsonText | ConvertFrom-Json -DateKind String
    }
    return $jsonText | ConvertFrom-Json
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $tempPath = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-ProjectPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    throw "No project Python with requests is available. Set TRADING_MVP_PYTHON."
}

function Invoke-JsonCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][object[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $output = & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $output
}

function Get-AutopilotState {
    $output = & pwsh -NoProfile -ExecutionPolicy Bypass -File $autopilotGuard -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot usage guard failed with exit code $LASTEXITCODE."
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $output
}

function Assert-SealedRuntimeTools {
    param([Parameter(Mandatory = $true)]$Plan)

    $runtimeTools = $Plan.sealed_schedule.runtime_tools
    if (-not $runtimeTools) {
        throw "Schedule plan has no sealed runtime tools."
    }
    $observed = @()
    foreach ($property in $runtimeTools.PSObject.Properties) {
        $toolName = [string]$property.Name
        $entry = $property.Value
        $toolPath = [string]$entry.path
        $expectedSha = ([string]$entry.sha256).ToLowerInvariant()
        if (-not $toolPath -or $expectedSha.Length -ne 64) {
            throw "Sealed runtime tool metadata is invalid: $toolName"
        }
        if (-not (Test-Path -LiteralPath $toolPath -PathType Leaf)) {
            throw "Sealed runtime tool is missing: $toolName path=$toolPath"
        }
        $actualSha = (Get-FileHash -LiteralPath $toolPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne $expectedSha) {
            throw "Sealed runtime tool hash mismatch: $toolName expected=$expectedSha observed=$actualSha"
        }
        $observed += [pscustomobject]@{
            name = $toolName
            path = [System.IO.Path]::GetFullPath($toolPath)
            sha256 = $actualSha
        }
    }

    $bindings = @{
        schedule_planner = $planCli
        quality_certifier = $qualityCli
    }
    foreach ($binding in $bindings.GetEnumerator()) {
        $entry = $runtimeTools.PSObject.Properties[$binding.Key].Value
        if (
            -not $entry -or
            [System.IO.Path]::GetFullPath([string]$entry.path) -ne
            [System.IO.Path]::GetFullPath([string]$binding.Value)
        ) {
            throw "Post-run runtime path is not the sealed $($binding.Key)."
        }
    }
    return @($observed)
}

function Assert-ExactSchedulePointer {
    param([Parameter(Mandatory = $true)]$Plan)

    if (-not (Test-Path -LiteralPath $SchedulePointerPath)) {
        throw "Dynamic PIT schedule pointer is missing: $SchedulePointerPath"
    }
    $pointer = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $SchedulePointerPath -Raw
    )
    if ([string]$pointer.status -ne "ACTIVE") {
        throw "Dynamic PIT schedule pointer is not ACTIVE."
    }
    if (
        [System.IO.Path]::GetFullPath([string]$pointer.plan_path) -ne
        [System.IO.Path]::GetFullPath($SchedulePlanPath)
    ) {
        throw "Dynamic PIT schedule pointer path mismatch."
    }
    if ([string]$pointer.plan_hash -ne $ExpectedSchedulePlanHash) {
        throw "Dynamic PIT schedule pointer hash mismatch."
    }
    if ([string]$pointer.hypothesis_id -ne [string]$Plan.hypothesis.id) {
        throw "Dynamic PIT schedule pointer hypothesis mismatch."
    }
    if ([string]$pointer.data_type -ne [string]$Plan.hypothesis.required_data_type) {
        throw "Dynamic PIT schedule pointer data_type mismatch."
    }
    if ([string]$pointer.collection_stage -ne [string]$Plan.collection_stage) {
        throw "Dynamic PIT schedule pointer collection_stage mismatch."
    }
    if (
        [System.IO.Path]::GetFullPath([string]$pointer.quality_ledger_path) -ne
        [System.IO.Path]::GetFullPath($QualityLedgerPath)
    ) {
        throw "Dynamic PIT schedule pointer quality ledger mismatch."
    }
}

function Write-Summary {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [Parameter(Mandatory = $true)][string]$NextAction,
        [hashtable]$Extra = @{}
    )

    $payload = [ordered]@{
        schema = "trading_mvp_pit_postrun_v1"
        project = "trading_mvp"
        run_id = $RunId
        decision = $Decision
        next_allowed_action = $NextAction
        schedule_plan_path = [System.IO.Path]::GetFullPath($SchedulePlanPath)
        schedule_plan_hash = $ExpectedSchedulePlanHash
        quality_ledger_path = [System.IO.Path]::GetFullPath($QualityLedgerPath)
        created_at = [DateTimeOffset]::Now.ToString("o")
        returns_read = $false
        pnl_read = $false
        oos_run = $false
        grid_search = $false
        live_orders = $false
        private_api_keys = $false
    }
    foreach ($entry in $Extra.GetEnumerator()) {
        $payload[$entry.Key] = $entry.Value
    }
    if ($script:reconciliationBinding) {
        $payload["reconciliation"] = $script:reconciliationBinding
    }
    Write-JsonAtomic -Object $payload -Path $summaryPath
    if (
        $script:reconciliationBinding -and
        $Decision -ne "PIT_POSTRUN_FAILED"
    ) {
        $summarySha256 = (
            Get-FileHash -LiteralPath $summaryPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        Resolve-ReconciledCriticalCheckpoint `
            -ReconciliationSummaryPath $summaryPath `
            -ReconciliationSummarySha256 $summarySha256
    }
    return [pscustomobject]$payload
}

function Set-CriticalCheckpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [Parameter(Mandatory = $true)][string]$Reason,
        [hashtable]$Evidence = @{}
    )

    $checkpoint = [ordered]@{
        schema = "trading_mvp_critical_checkpoint_v1"
        status = "USER_REVIEW_REQUIRED"
        project = "trading_mvp"
        decision = $Decision
        reason = $Reason
        run_id = $RunId
        created_at = [DateTimeOffset]::Now.ToString("o")
        evidence = $Evidence
        prohibited_until_review = @(
            "new hypothesis",
            "OOS collection or evaluation",
            "execution probe",
            "paper forward",
            "live orders",
            "private API keys",
            "real capital",
            "leverage or margin"
        )
    }
    Write-JsonAtomic -Object $checkpoint -Path $CriticalCheckpointPath
}

function Resolve-ReconciledCriticalCheckpoint {
    param(
        [Parameter(Mandatory = $true)][string]$ReconciliationSummaryPath,
        [Parameter(Mandatory = $true)][string]$ReconciliationSummarySha256
    )

    if (-not (Test-Path -LiteralPath $CriticalCheckpointPath -PathType Leaf)) {
        throw "Matching PIT_POSTRUN_FAILED critical checkpoint is missing."
    }
    $checkpoint = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $CriticalCheckpointPath -Raw
    )
    if (
        [string]$checkpoint.schema -ne "trading_mvp_critical_checkpoint_v1" -or
        [string]$checkpoint.project -ne "trading_mvp"
    ) {
        throw "Critical checkpoint schema or project mismatch."
    }
    if (
        [string]$checkpoint.status -ne "USER_REVIEW_REQUIRED" -or
        [string]$checkpoint.decision -ne "PIT_POSTRUN_FAILED" -or
        [string]$checkpoint.run_id -ne $RunId
    ) {
        return
    }

    $checkpointSha256 = (
        Get-FileHash -LiteralPath $CriticalCheckpointPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $archiveRoot = Join-Path $repoRoot "docs\agent-log\archived-critical-checkpoints"
    New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
    $archivePath = Join-Path $archiveRoot (
        "$RunId.pit-postrun-failed.$($checkpointSha256.Substring(0, 16)).json"
    )
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        $archiveSha256 = (
            Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if ($archiveSha256 -ne $checkpointSha256) {
            throw "Archived failed critical checkpoint hash mismatch."
        }
    } else {
        Copy-Item -LiteralPath $CriticalCheckpointPath -Destination $archivePath
    }

    if (Test-Path -LiteralPath $reconciliationResolutionPath -PathType Leaf) {
        throw "PIT post-run reconciliation resolution already exists."
    }
    $resolution = [ordered]@{
        schema = "trading_mvp_pit_postrun_reconciliation_resolution_v1"
        project = "trading_mvp"
        run_id = $RunId
        status = "RESOLVED"
        decision = "PIT_POSTRUN_RECOVERED"
        resolved_at = [DateTimeOffset]::Now.ToString("o")
        failed_checkpoint_path = [System.IO.Path]::GetFullPath($archivePath)
        failed_checkpoint_sha256 = $checkpointSha256
        postrun_reconciliation_summary_path = (
            [System.IO.Path]::GetFullPath($ReconciliationSummaryPath)
        )
        postrun_reconciliation_summary_sha256 = $ReconciliationSummarySha256
        returns_read = $false
        pnl_read = $false
        oos_run = $false
        new_collector_started = $false
    }
    Write-JsonAtomic -Object $resolution -Path $reconciliationResolutionPath

    $resolvedCheckpoint = [ordered]@{
        schema = "trading_mvp_critical_checkpoint_v1"
        status = "RESOLVED"
        project = "trading_mvp"
        decision = "PIT_POSTRUN_RECOVERED"
        reason = "Exact final output was verified and postrun was reconciled without replacing the failed evidence."
        run_id = $RunId
        created_at = [string]$checkpoint.created_at
        resolved_at = [string]$resolution.resolved_at
        evidence = [ordered]@{
            failed_checkpoint_path = [System.IO.Path]::GetFullPath($archivePath)
            failed_checkpoint_sha256 = $checkpointSha256
            postrun_reconciliation_summary_path = (
                [System.IO.Path]::GetFullPath($ReconciliationSummaryPath)
            )
            postrun_reconciliation_summary_sha256 = $ReconciliationSummarySha256
            resolution_path = [System.IO.Path]::GetFullPath($reconciliationResolutionPath)
        }
        prohibited_until_review = @()
    }
    Write-JsonAtomic -Object $resolvedCheckpoint -Path $CriticalCheckpointPath
}

function Get-AcceptedDates {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedHypothesisId,
        [Parameter(Mandatory = $true)][string]$ExpectedDataType,
        [Parameter(Mandatory = $true)][string]$ExpectedContractHash
    )

    if (-not (Test-Path -LiteralPath $QualityLedgerPath)) {
        return @()
    }
    $dates = @()
    foreach ($line in Get-Content -LiteralPath $QualityLedgerPath) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $entry = ConvertFrom-JsonPreserveDateStrings -InputJson $line
        if (
            [string]$entry.hypothesis_id -ne $ExpectedHypothesisId -or
            [string]$entry.data_type -ne $ExpectedDataType -or
            [string]$entry.hypothesis_contract_sha256 -ne $ExpectedContractHash
        ) {
            throw "Quality ledger contains an entry from another frozen hypothesis/data/contract track."
        }
        if ($entry.technical_quality_accepted -eq $true) {
            $dates += [string]$entry.scheduled_date
        }
    }
    return @($dates | Sort-Object -Unique)
}

function Assert-TrainFeasibilityManifestBinding {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$ExpectedRunId,
        [Parameter(Mandatory = $true)][string]$ExpectedHypothesisId,
        [Parameter(Mandatory = $true)][string]$ExpectedDataType,
        [Parameter(Mandatory = $true)][string]$ExpectedContractHash,
        [Parameter(Mandatory = $true)][string]$ExpectedLedgerHash,
        [Parameter(Mandatory = $true)][int]$ExpectedTrainDates
    )

    if (
        $Manifest.final -ne $true -or
        [string]$Manifest.run_id -ne $ExpectedRunId -or
        [string]$Manifest.hypothesis_id -ne $ExpectedHypothesisId
    ) {
        throw "Train-only feasibility manifest identity/finality mismatch."
    }
    if (
        [string]$Manifest.verdict -notin @("FEASIBLE_FOR_OOS", "INFEASIBLE_ON_CURRENT_DATA") -or
        [int]$Manifest.train_dates_read -ne $ExpectedTrainDates -or
        [int]$Manifest.oos_dates_read -ne 0 -or
        $Manifest.returns_read -ne $false -or
        $Manifest.pnl_computed -ne $false -or
        $Manifest.network_access -ne $false -or
        $Manifest.grid_search -ne $false -or
        $Manifest.retune -ne $false -or
        [int]$Manifest.deterministic_repeats -ne 2 -or
        $Manifest.deterministic_repeats_match -ne $true -or
        ([string]$Manifest.deterministic_result_hash).Length -ne 64
    ) {
        throw "Train-only feasibility manifest violated the frozen train/OOS embargo contract."
    }

    $artifactRootFull = [System.IO.Path]::GetFullPath($FeasibilityArtifactRoot).TrimEnd('\') + '\'
    $boundPaths = [ordered]@{
        plan = [string]$Manifest.plan_path
        feasibility = [string]$Manifest.feasibility_path
        repeat_feasibility = [string]$Manifest.repeat_feasibility_path
    }
    if ([string]$Manifest.verdict -eq "FEASIBLE_FOR_OOS") {
        $boundPaths["oos_schedule"] = [string]$Manifest.oos_schedule_path
    } elseif ($Manifest.oos_schedule_path) {
        throw "Infeasible train manifest must not expose an OOS schedule."
    }
    foreach ($entry in $boundPaths.GetEnumerator()) {
        if (-not $entry.Value) {
            throw "Train-only feasibility manifest is missing $($entry.Key) path."
        }
        $fullPath = [System.IO.Path]::GetFullPath($entry.Value)
        if (-not $fullPath.StartsWith($artifactRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Train-only feasibility manifest path escapes the artifact root: $fullPath"
        }
        if (-not (Test-Path -LiteralPath $fullPath)) {
            throw "Train-only feasibility bound artifact is missing: $fullPath"
        }
    }

    $hashBindings = @(
        @([string]$Manifest.plan_path, [string]$Manifest.plan_file_sha256, "plan"),
        @([string]$Manifest.feasibility_path, [string]$Manifest.feasibility_file_sha256, "feasibility"),
        @([string]$Manifest.repeat_feasibility_path, [string]$Manifest.repeat_feasibility_file_sha256, "repeat feasibility")
    )
    if ([string]$Manifest.verdict -eq "FEASIBLE_FOR_OOS") {
        $hashBindings += ,@(
            [string]$Manifest.oos_schedule_path,
            [string]$Manifest.oos_schedule_file_sha256,
            "OOS schedule"
        )
    }
    foreach ($binding in $hashBindings) {
        $actualHash = (Get-FileHash -LiteralPath $binding[0] -Algorithm SHA256).Hash.ToLowerInvariant()
        if ([string]$binding[1] -ne $actualHash) {
            throw "Train-only feasibility $($binding[2]) file hash mismatch."
        }
    }

    $inputPlan = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath ([string]$Manifest.plan_path) -Raw
    )
    $sealedInput = $inputPlan.sealed_input
    if (
        -not $sealedInput -or
        [string]$inputPlan.plan_hash -ne [string]$Manifest.plan_hash -or
        [string]$inputPlan.sealed_input_hash -ne [string]$Manifest.plan_hash -or
        [string]$sealedInput.plan_stage -ne "train_feasibility" -or
        [string]$sealedInput.hypothesis_id -ne $ExpectedHypothesisId -or
        [string]$sealedInput.data_type -ne $ExpectedDataType -or
        [string]$sealedInput.hypothesis_contract_sha256 -ne $ExpectedContractHash -or
        [System.IO.Path]::GetFullPath([string]$sealedInput.quality_ledger.path) -ne
        [System.IO.Path]::GetFullPath($QualityLedgerPath) -or
        [string]$sealedInput.quality_ledger.file_sha256_at_plan -ne $ExpectedLedgerHash -or
        @($sealedInput.split.train_dates).Count -ne $ExpectedTrainDates -or
        @($sealedInput.split.oos_dates).Count -ne 0
    ) {
        throw "Train-only feasibility input plan is not bound to the exact ledger/contract/train split."
    }

    foreach ($resultPath in @(
        [string]$Manifest.feasibility_path,
        [string]$Manifest.repeat_feasibility_path
    )) {
        $result = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -LiteralPath $resultPath -Raw
        )
        if (
            [string]$result.plan_hash -ne [string]$Manifest.plan_hash -or
            [string]$result.verdict -ne [string]$Manifest.verdict -or
            [string]$result.deterministic_result_hash -ne [string]$Manifest.deterministic_result_hash -or
            [int]$result.train_dates_read -ne $ExpectedTrainDates -or
            [int]$result.oos_dates_read -ne 0 -or
            $result.returns_read -ne $false -or
            $result.pnl_computed -ne $false -or
            $result.network_access -ne $false -or
            $result.grid_search -ne $false -or
            $result.retune -ne $false
        ) {
            throw "Train-only feasibility result artifact binding/embargo mismatch."
        }
    }

    if ([string]$Manifest.verdict -eq "FEASIBLE_FOR_OOS") {
        $oosSchedule = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -LiteralPath ([string]$Manifest.oos_schedule_path) -Raw
        )
        if (
            [string]$oosSchedule.plan_hash -ne [string]$Manifest.oos_schedule_plan_hash -or
            [string]$oosSchedule.mode -ne "PlanOnly" -or
            [string]$oosSchedule.collection_stage -ne "oos_accrual" -or
            $oosSchedule.schedule_approved -ne $false -or
            $oosSchedule.collection_started -ne $false -or
            $oosSchedule.network_access -ne $false -or
            $oosSchedule.oos_returns_read -ne $false -or
            $oosSchedule.pnl_or_returns_read -ne $false -or
            $oosSchedule.grid_search -ne $false -or
            $oosSchedule.retune -ne $false
        ) {
            throw "Train-only feasibility OOS schedule is not an exact inactive PlanOnly."
        }
    }
}

function Assert-WithinRuntime {
    param([Parameter(Mandatory = $true)][DateTimeOffset]$StartedAt)

    if (([DateTimeOffset]::Now - $StartedAt).TotalSeconds -ge $MaxRuntimeSec) {
        throw "PIT post-run exceeded MaxRuntimeSec=$MaxRuntimeSec."
    }
}

function Get-RemainingRuntimeSec {
    param([Parameter(Mandatory = $true)][DateTimeOffset]$StartedAt)

    $remaining = [int][Math]::Floor(
        $MaxRuntimeSec - ([DateTimeOffset]::Now - $StartedAt).TotalSeconds
    )
    if ($remaining -lt 1) {
        throw "PIT post-run has no remaining runtime budget."
    }
    return $remaining
}

foreach ($required in @(
    $SchedulePlanPath,
    $QualityLedgerPath,
    $planCli,
    $qualityDryRunCli,
    $qualityCli,
    $autopilotGuard,
    $gateChecker,
    $feasibilityTool,
    $gatePath
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required PIT post-run input is missing: $required"
    }
}

$startedAt = [DateTimeOffset]::Now
$python = Resolve-ProjectPython
$validation = Invoke-JsonCommand -FilePath $python -Label "Night schedule validation" -ArgumentList @(
    $planCli,
    "validate",
    "--plan", $SchedulePlanPath,
    "--expected-plan-hash", $ExpectedSchedulePlanHash
)
if ([string]$validation.verdict -ne "VALID") {
    throw "Night schedule validation did not return VALID."
}

$plan = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $SchedulePlanPath -Raw)
$sealedRuntimeTools = Assert-SealedRuntimeTools -Plan $plan
$segments = @($plan.segments)
$matched = @($segments | Where-Object { [string]$_.run_id -eq $RunId })
if ($matched.Count -ne 1) {
    throw "Expected exactly one schedule segment for RunId=$RunId, observed=$($matched.Count)."
}
$segment = $matched[0]
$expectedHypothesisId = [string]$plan.hypothesis.id
$expectedDataType = [string]$plan.hypothesis.required_data_type
$expectedContractHash = [string]$plan.sealed_schedule.hypothesis_contract_sha256
if (-not $expectedContractHash) {
    throw "Frozen hypothesis contract hash is missing from the schedule plan."
}
Assert-ExactSchedulePointer -Plan $plan

if ($PlanOnly -and $ReconcileFailedSummary) {
    throw "PlanOnly cannot be combined with ReconcileFailedSummary."
}
if ($PlanOnly) {
    $acceptedDates = Get-AcceptedDates `
        -ExpectedHypothesisId $expectedHypothesisId `
        -ExpectedDataType $expectedDataType `
        -ExpectedContractHash $expectedContractHash
    [ordered]@{
        schema = "trading_mvp_pit_postrun_plan_v1"
        decision = "PLAN_VALIDATED"
        run_id = $RunId
        schedule_plan_path = [System.IO.Path]::GetFullPath($SchedulePlanPath)
        schedule_plan_hash = $ExpectedSchedulePlanHash
        accepted_distinct_dates = $acceptedDates.Count
        train_target_distinct_dates = [int]$plan.sealed_schedule.quality_policy.train_feasibility_distinct_days
        sealed_runtime_tools_verified = $sealedRuntimeTools.Count
        actions = @(
            "weekly usage guard",
            "technical quality dry-run",
            "idempotent sealed quality commit",
            "wait for next date or request an exact hash-bound schedule extension",
            "visible deterministic train-only feasibility exactly at the frozen date target"
        )
        returns_read = $false
        pnl_read = $false
        mutation = $false
    } | ConvertTo-Json -Depth 20
    exit 0
}

if ($ReconcileFailedSummary) {
    if (-not (Test-Path -LiteralPath $canonicalSummaryPath -PathType Leaf)) {
        throw "Canonical PIT post-run failure summary is missing."
    }
    if (Test-Path -LiteralPath $reconciliationSummaryPath -PathType Leaf) {
        throw "PIT post-run reconciliation already exists; refusing overwrite."
    }
    $failedSummary = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $canonicalSummaryPath -Raw
    )
    if (
        [string]$failedSummary.schema -ne "trading_mvp_pit_postrun_v1" -or
        [string]$failedSummary.project -ne "trading_mvp" -or
        [string]$failedSummary.run_id -ne $RunId -or
        [string]$failedSummary.schedule_plan_hash -ne $ExpectedSchedulePlanHash -or
        [System.IO.Path]::GetFullPath([string]$failedSummary.schedule_plan_path) -ne
        [System.IO.Path]::GetFullPath($SchedulePlanPath) -or
        [System.IO.Path]::GetFullPath([string]$failedSummary.quality_ledger_path) -ne
        [System.IO.Path]::GetFullPath($QualityLedgerPath) -or
        [string]$failedSummary.decision -ne "PIT_POSTRUN_FAILED" -or
        [string]$failedSummary.failure -ne
        "RuntimeException: PIT post-run requires final, complete, successfully completed output." -or
        $failedSummary.returns_read -ne $false -or
        $failedSummary.pnl_read -ne $false -or
        $failedSummary.oos_run -ne $false -or
        $failedSummary.grid_search -ne $false -or
        $failedSummary.live_orders -ne $false -or
        $failedSummary.private_api_keys -ne $false
    ) {
        throw "Canonical PIT post-run failure is not eligible for exact reconciliation."
    }
    if (-not (Test-Path -LiteralPath $CriticalCheckpointPath -PathType Leaf)) {
        throw "Matching PIT_POSTRUN_FAILED critical checkpoint is missing."
    }
    $failedCheckpoint = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $CriticalCheckpointPath -Raw
    )
    if (
        [string]$failedCheckpoint.schema -ne "trading_mvp_critical_checkpoint_v1" -or
        [string]$failedCheckpoint.status -ne "USER_REVIEW_REQUIRED" -or
        [string]$failedCheckpoint.project -ne "trading_mvp" -or
        [string]$failedCheckpoint.decision -ne "PIT_POSTRUN_FAILED" -or
        [string]$failedCheckpoint.run_id -ne $RunId -or
        [string]$failedCheckpoint.reason -ne [string]$failedSummary.failure
    ) {
        throw "Current critical checkpoint does not authorize exact reconciliation."
    }
    $failedSummarySha256 = (
        Get-FileHash -LiteralPath $canonicalSummaryPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $script:reconciliationBinding = [ordered]@{
        schema = "trading_mvp_pit_postrun_reconciliation_v1"
        supersedes_summary_path = [System.IO.Path]::GetFullPath($canonicalSummaryPath)
        supersedes_summary_sha256 = $failedSummarySha256
        reconciliation_reason = "recover_exact_final_output_after_control_plane_readiness_mismatch"
        authorization = "explicit_ReconcileFailedSummary_after_user_review"
    }
    $summaryPath = $reconciliationSummaryPath
} elseif (Test-Path -LiteralPath $canonicalSummaryPath -PathType Leaf) {
    throw "Canonical PIT post-run summary already exists; refusing overwrite."
}

try {
    $autopilot = Get-AutopilotState
    if ($autopilot.stop_new_actions -eq $true) {
        $summary = Write-Summary `
            -Decision ([string]$autopilot.decision) `
            -NextAction "wait_for_fresh_weekly_quota_above_15_percent_then_retry_postrun" `
            -Extra @{
                weekly_remaining_percent = $autopilot.usage.remaining_percent
                weekly_reset = $autopilot.usage.resets_at_local
            }
        Write-Host "[pit-postrun] paused by weekly usage guard" -ForegroundColor Yellow
        $summary | ConvertTo-Json -Depth 20
        exit 0
    }

    $observedGateJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Active-run gate checker failed with exit code $LASTEXITCODE."
    }
    $observedGate = ConvertFrom-JsonPreserveDateStrings -InputJson $observedGateJson
    if ([string]$observedGate.status -ne "READY_FOR_POSTPROCESS") {
        throw "PIT post-run requires READY_FOR_POSTPROCESS, observed=$($observedGate.status)."
    }
    if ([string]$observedGate.run_id -ne $RunId) {
        throw "PIT post-run current-run pointer mismatch: expected=$RunId observed=$($observedGate.run_id)."
    }
    if (
        $observedGate.final -ne $true -or
        $observedGate.primary_output_complete -ne $true -or
        [string]$observedGate.stop_reason -ne "completed"
    ) {
        throw "PIT post-run requires final, complete, successfully completed output."
    }

    $gate = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $gatePath -Raw)
    $gateStatus = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
    if ($gateStatus -ne "READY_FOR_POSTPROCESS") {
        throw "PIT post-run requires READY_FOR_POSTPROCESS, observed=$gateStatus."
    }
    if ([string]$gate.run_id -ne $RunId) {
        throw "PIT post-run gate run_id mismatch: expected=$RunId observed=$($gate.run_id)."
    }
    if (
        $gate.final -ne $true -or
        $gate.primary_output_complete -ne $true -or
        [string]$gate.stop_reason -ne "completed"
    ) {
        throw "PIT post-run active gate is not final and complete."
    }
    $expectedManifestPath = Join-Path ([string]$segment.output_dir) "manifest.json"
    $expectedSnapshotsPath = Join-Path ([string]$segment.output_dir) "snapshots.jsonl"
    $expectedCyclesPath = Join-Path ([string]$segment.output_dir) "cycles.jsonl"
    $expectedStatePath = Join-Path ([string]$segment.output_dir) "universe_state.json"
    if (
        [System.IO.Path]::GetFullPath([string]$observedGate.manifest_path) -ne
        [System.IO.Path]::GetFullPath($expectedManifestPath)
    ) {
        throw "PIT post-run checker manifest path does not match the exact schedule segment."
    }
    if (
        -not $observedGate.output -or
        [System.IO.Path]::GetFullPath([string]$observedGate.output.path) -ne
        [System.IO.Path]::GetFullPath($expectedSnapshotsPath)
    ) {
        throw "PIT post-run checker output path does not match the exact schedule segment."
    }
    if (
        [System.IO.Path]::GetFullPath([string]$gate.manifest_path) -ne
        [System.IO.Path]::GetFullPath($expectedManifestPath)
    ) {
        throw "PIT post-run manifest path does not match the exact schedule segment."
    }
    if (-not (Test-Path -LiteralPath $expectedManifestPath)) {
        throw "PIT post-run exact segment manifest is missing: $expectedManifestPath"
    }
    $manifest = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $expectedManifestPath -Raw
    )
    if (
        [string]$manifest.schema -ne "pit_universe_snapshot_manifest_v2" -or
        [string]$manifest.run_id -ne $RunId -or
        [string]$manifest.status -ne "COMPLETED" -or
        $manifest.final -ne $true -or
        $manifest.incomplete -ne $false
    ) {
        throw "PIT post-run exact segment manifest is not final and complete."
    }
    $manifestOutputBindings = @(
        @([string]$manifest.snapshots_path, $expectedSnapshotsPath),
        @([string]$manifest.cycles_path, $expectedCyclesPath),
        @([string]$manifest.state_path, $expectedStatePath)
    )
    foreach ($binding in $manifestOutputBindings) {
        if (
            [System.IO.Path]::GetFullPath($binding[0]) -ne
            [System.IO.Path]::GetFullPath($binding[1]) -or
            -not (Test-Path -LiteralPath $binding[1] -PathType Leaf)
        ) {
            throw "PIT post-run manifest output binding mismatch."
        }
    }
    $approvedSchedule = $gate.approved_night_schedule
    if (
        -not $approvedSchedule -or
        [string]$approvedSchedule.status -ne "ACTIVE" -or
        [string]$approvedSchedule.plan_hash -ne $ExpectedSchedulePlanHash -or
        [System.IO.Path]::GetFullPath([string]$approvedSchedule.plan_path) -ne
        [System.IO.Path]::GetFullPath($SchedulePlanPath)
    ) {
        throw "PIT post-run active gate is not bound to the exact approved schedule."
    }

    New-Item -ItemType Directory -Path $QualityReportRoot -Force | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $dryRunPath = Join-Path $QualityReportRoot "$RunId.quality-dry-run.$stamp.json"
    $qualityPath = Join-Path $QualityReportRoot "$RunId.quality.$stamp.json"

    Write-Host "[pit-postrun] technical quality dry-run" -ForegroundColor Cyan
    $dryRun = Invoke-JsonCommand -FilePath $python -Label "PIT quality dry-run" -ArgumentList @(
        $qualityDryRunCli,
        "--plan", $SchedulePlanPath,
        "--expected-plan-hash", $ExpectedSchedulePlanHash,
        "--approval-record-root", $ApprovalRecordRoot,
        "--ledger", $QualityLedgerPath,
        "--output", $dryRunPath
    )
    if ([string]$dryRun.decision -ne "PIT_SEGMENT_QUALITY_DRY_RUN_ACCEPTED") {
        Set-CriticalCheckpoint `
            -Decision ([string]$dryRun.decision) `
            -Reason "Technical quality did not accept the completed PIT segment." `
            -Evidence @{
                dry_run_report = $dryRunPath
                segments_rejected = $dryRun.segments_rejected
            }
        $summary = Write-Summary `
            -Decision ([string]$dryRun.decision) `
            -NextAction "user_review_required_before_any_new_collector" `
            -Extra @{ dry_run_report = $dryRunPath }
        Write-Host "[pit-postrun] CRITICAL: $($dryRun.decision)" -ForegroundColor Red
        $summary | ConvertTo-Json -Depth 20
        exit 0
    }

    Assert-WithinRuntime -StartedAt $startedAt
    Write-Host "[pit-postrun] committing sealed technical certification" -ForegroundColor Cyan
    $quality = Invoke-JsonCommand -FilePath $python -Label "PIT quality commit" -ArgumentList @(
        $qualityCli,
        "--plan", $SchedulePlanPath,
        "--expected-plan-hash", $ExpectedSchedulePlanHash,
        "--approval-record-root", $ApprovalRecordRoot,
        "--ledger", $QualityLedgerPath,
        "--output", $qualityPath
    )
    if ([int]$quality.segments_rejected -gt 0) {
        throw "Sealed quality commit reported rejected segments."
    }

    $acceptedDates = Get-AcceptedDates `
        -ExpectedHypothesisId $expectedHypothesisId `
        -ExpectedDataType $expectedDataType `
        -ExpectedContractHash $expectedContractHash
    $trainTarget = [int]$plan.sealed_schedule.quality_policy.train_feasibility_distinct_days
    Write-Host "[pit-postrun] accepted_dates=$($acceptedDates.Count)/$trainTarget" -ForegroundColor Green

    if ($acceptedDates.Count -gt $trainTarget) {
        Set-CriticalCheckpoint `
            -Decision "TRAIN_DATE_TARGET_OVERSHOOT" `
            -Reason "Accepted PIT dates exceed the frozen train-feasibility target." `
            -Evidence @{ accepted_dates = $acceptedDates.Count; target = $trainTarget; quality_report = $qualityPath }
        $summary = Write-Summary `
            -Decision "TRAIN_DATE_TARGET_OVERSHOOT" `
            -NextAction "user_review_required" `
            -Extra @{ accepted_distinct_dates = $acceptedDates.Count; quality_report = $qualityPath }
        $summary | ConvertTo-Json -Depth 20
        exit 0
    }

    if ($acceptedDates.Count -eq $trainTarget) {
        Assert-WithinRuntime -StartedAt $startedAt
        $autopilot = Get-AutopilotState
        if ($autopilot.stop_new_actions -eq $true) {
            $summary = Write-Summary `
                -Decision ([string]$autopilot.decision) `
                -NextAction "run_train_feasibility_after_weekly_quota_reset" `
                -Extra @{ accepted_distinct_dates = $acceptedDates.Count; quality_report = $qualityPath }
            $summary | ConvertTo-Json -Depth 20
            exit 0
        }

        $ledgerHash = (Get-FileHash -LiteralPath $QualityLedgerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $feasibilityRunId = "pit_train_feasibility_$($ledgerHash.Substring(0, 12))"
        $feasibilityManifest = Join-Path $FeasibilityArtifactRoot "$feasibilityRunId.manifest.json"
        if (-not (Test-Path -LiteralPath $feasibilityManifest)) {
            $feasibilityRuntimeSec = [Math]::Min(1800, (Get-RemainingRuntimeSec -StartedAt $startedAt))
            Write-Host "[pit-postrun] opening visible deterministic train-only feasibility" -ForegroundColor Cyan
            & pwsh -NoProfile -ExecutionPolicy Bypass -File $feasibilityTool `
                -RunId $feasibilityRunId `
                -ArtifactRoot $FeasibilityArtifactRoot `
                -QualityLedgerPath $QualityLedgerPath `
                -MaxRuntimeSec $feasibilityRuntimeSec `
                -HoldOpenSec 0
            if ($LASTEXITCODE -ne 0) {
                throw "Visible train-only feasibility failed with exit code $LASTEXITCODE."
            }
        }
        if (-not (Test-Path -LiteralPath $feasibilityManifest)) {
            throw "Train-only feasibility returned without a final manifest: $feasibilityManifest"
        }

        $feasibility = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -LiteralPath $feasibilityManifest -Raw
        )
        Assert-TrainFeasibilityManifestBinding `
            -Manifest $feasibility `
            -ExpectedRunId $feasibilityRunId `
            -ExpectedHypothesisId $expectedHypothesisId `
            -ExpectedDataType $expectedDataType `
            -ExpectedContractHash $expectedContractHash `
            -ExpectedLedgerHash $ledgerHash `
            -ExpectedTrainDates $trainTarget
        $verdict = [string]$feasibility.verdict
        Set-CriticalCheckpoint `
            -Decision $verdict `
            -Reason "Frozen train-only feasibility produced a hypothesis-level verdict." `
            -Evidence @{
                manifest = $feasibilityManifest
                deterministic_result_hash = $feasibility.deterministic_result_hash
                oos_schedule_path = $feasibility.oos_schedule_path
                oos_schedule_plan_hash = $feasibility.oos_schedule_plan_hash
            }
        $summary = Write-Summary `
            -Decision $verdict `
            -NextAction "user_review_required_before_oos_or_branch_closure" `
            -Extra @{
                accepted_distinct_dates = $acceptedDates.Count
                quality_report = $qualityPath
                feasibility_manifest = $feasibilityManifest
            }
        Write-Host "[pit-postrun] CRITICAL VERDICT=$verdict" -ForegroundColor Yellow
        $summary | ConvertTo-Json -Depth 20
        exit 0
    }

    $pendingSegments = @(
        $segments | Where-Object {
            $scheduledDate = ([string]$_.start_local).Split("T", 2)[0]
            $acceptedDates -notcontains $scheduledDate
        }
    )
    if ($pendingSegments.Count -gt 0) {
        $summary = Write-Summary `
            -Decision "WAITING_EVENT" `
            -NextAction "run_next_due_hash_bound_visible_segment" `
            -Extra @{
                accepted_distinct_dates = $acceptedDates.Count
                train_target_distinct_dates = $trainTarget
                pending_schedule_segments = $pendingSegments.Count
                next_run_id = [string]$pendingSegments[0].run_id
                next_start_local = [string]$pendingSegments[0].start_local
                quality_report = $qualityPath
            }
        Write-Host "[pit-postrun] waiting for next independent observation date" -ForegroundColor Cyan
        $summary | ConvertTo-Json -Depth 20
        exit 0
    }

    Assert-WithinRuntime -StartedAt $startedAt
    $autopilot = Get-AutopilotState
    if ($autopilot.stop_new_actions -eq $true) {
        $summary = Write-Summary `
            -Decision ([string]$autopilot.decision) `
            -NextAction "refresh_horizon_after_weekly_quota_reset_then_request_exact_schedule_approval" `
            -Extra @{ accepted_distinct_dates = $acceptedDates.Count; quality_report = $qualityPath }
        $summary | ConvertTo-Json -Depth 20
        exit 0
    }

    $remainingDates = $trainTarget - $acceptedDates.Count
    Set-CriticalCheckpoint `
        -Decision "PIT_SCHEDULE_EXTENSION_REQUIRES_EXACT_USER_APPROVAL" `
        -Reason "The approved schedule is exhausted before the frozen train-date target. Refresh the horizon and request exact hash-bound user approval; post-run must not self-approve or advance the pointer." `
        -Evidence @{
            accepted_distinct_dates = $acceptedDates.Count
            train_target_distinct_dates = $trainTarget
            remaining_distinct_dates = $remainingDates
            exhausted_plan_path = [System.IO.Path]::GetFullPath($SchedulePlanPath)
            exhausted_plan_hash = $ExpectedSchedulePlanHash
            schedule_pointer_path = [System.IO.Path]::GetFullPath($SchedulePointerPath)
            automatic_approval = $false
            pointer_advanced = $false
        }
    $summary = Write-Summary `
        -Decision "PIT_SCHEDULE_EXTENSION_REQUIRES_EXACT_USER_APPROVAL" `
        -NextAction "refresh_horizon_then_request_exact_hash_bound_schedule_approval" `
        -Extra @{
            accepted_distinct_dates = $acceptedDates.Count
            train_target_distinct_dates = $trainTarget
            remaining_distinct_dates = $remainingDates
            schedule_pointer_path = $SchedulePointerPath
            quality_report = $qualityPath
            automatic_approval = $false
            pointer_advanced = $false
        }
    Write-Host "[pit-postrun] exact user approval required for any schedule extension" -ForegroundColor Yellow
    $summary | ConvertTo-Json -Depth 20
    exit 0
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
        Write-Host "[pit-postrun] FAILED after durable summary was written: $message" -ForegroundColor Red
        exit 1
    }
    Set-CriticalCheckpoint `
        -Decision "PIT_POSTRUN_FAILED" `
        -Reason $message `
        -Evidence @{ schedule_plan_path = $SchedulePlanPath; schedule_plan_hash = $ExpectedSchedulePlanHash }
    $summary = Write-Summary `
        -Decision "PIT_POSTRUN_FAILED" `
        -NextAction "user_review_required_before_any_new_collector" `
        -Extra @{ failure = $message }
    Write-Host "[pit-postrun] FAILED: $message" -ForegroundColor Red
    $summary | ConvertTo-Json -Depth 20
    exit 1
}
