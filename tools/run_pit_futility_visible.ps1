[CmdletBinding()]
param(
    [string]$RunId = "",
    [string]$ArtifactRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\pit-futility",
    [string]$QualityLedgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl",
    [string]$HypothesisBankPath = "",
    [string]$Hypothesis = "pit_universe_membership_drift_reversion_v1",
    [string]$PlanPath = "",
    [string]$ResultPath = "",
    [string]$ManifestPath = "",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [ValidateRange(1, 1800)]
    [int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 600)]
    [int]$HoldOpenSec = 60,
    [string]$ApprovedNotLaterThan = "",
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RunMvpPath = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
if (-not $HypothesisBankPath) {
    $HypothesisBankPath = Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
}
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json"
}

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Value)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    return [System.Convert]::ToHexString($hash).ToLowerInvariant()
}

function Get-FileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temp = "$fullPath.$PID.$([System.Guid]::NewGuid().ToString('N')).tmp"
    try {
        $json = $Value | ConvertTo-Json -Depth 30
        [System.IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temp -Destination $fullPath -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Get-AcceptedDateInfo {
    if (-not (Test-Path -LiteralPath $QualityLedgerPath)) {
        throw "Quality ledger not found: $QualityLedgerPath"
    }
    if (-not (Test-Path -LiteralPath $HypothesisBankPath)) {
        throw "Hypothesis bank not found: $HypothesisBankPath"
    }
    $bank = Get-Content -LiteralPath $HypothesisBankPath -Raw | ConvertFrom-Json
    $matches = @($bank.hypotheses | Where-Object { [string]$_.id -eq $Hypothesis })
    if ($matches.Count -ne 1) {
        throw "Hypothesis bank must contain exactly one entry for $Hypothesis."
    }
    $hypothesisEntry = $matches[0]
    $expectedDataType = [string]$hypothesisEntry.required_data_type
    $expectedContractHash = [string]$hypothesisEntry.contract.contract_hash
    if (-not $expectedDataType -or -not $expectedContractHash) {
        throw "Hypothesis bank entry is missing required_data_type or contract_hash."
    }
    $acceptedByDate = @{}
    foreach ($line in [System.IO.File]::ReadLines([System.IO.Path]::GetFullPath($QualityLedgerPath))) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $row = $line | ConvertFrom-Json } catch { throw "Invalid quality ledger JSONL: $($_.Exception.Message)" }
        if (
            [string]$row.hypothesis_id -eq $Hypothesis -and
            [string]$row.data_type -eq $expectedDataType
        ) {
            if ([string]$row.hypothesis_contract_sha256 -ne $expectedContractHash) {
                throw "Quality certification hypothesis contract hash mismatch."
            }
            if ($row.technical_quality_accepted -ne $true) { continue }
            $scheduledDate = [string]$row.scheduled_date
            $parsedDate = [datetime]::MinValue
            if (-not [datetime]::TryParseExact(
                $scheduledDate,
                "yyyy-MM-dd",
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::None,
                [ref]$parsedDate
            )) {
                throw "Invalid scheduled_date in quality ledger: $scheduledDate"
            }
            if ($acceptedByDate.ContainsKey($scheduledDate)) {
                throw "Duplicate accepted certification date: $scheduledDate"
            }
            $certificationId = [string]$row.certification_id
            if (-not $certificationId) {
                throw "Accepted quality certification is missing certification_id: $scheduledDate"
            }
            $acceptedByDate[$scheduledDate] = $certificationId
        }
    }
    $ordered = @($acceptedByDate.Keys | Sort-Object)
    $certificationIds = @($ordered | ForEach-Object { [string]$acceptedByDate[$_] })
    return [ordered]@{
        count = $ordered.Count
        dates = $ordered
        certification_ids = $certificationIds
        data_type = $expectedDataType
        hypothesis_contract_sha256 = $expectedContractHash
    }
}

$ArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
$QualityLedgerPath = [System.IO.Path]::GetFullPath($QualityLedgerPath)
$HypothesisBankPath = [System.IO.Path]::GetFullPath($HypothesisBankPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
$dateInfo = Get-AcceptedDateInfo
if (-not $RunId) {
    $identityValues = if ($dateInfo.count -ge 10) {
        @($dateInfo.certification_ids | Select-Object -First 10)
    } else {
        @($Hypothesis, $dateInfo.hypothesis_contract_sha256) + @($dateInfo.certification_ids)
    }
    $identityHash = Get-TextSha256 -Value ($identityValues -join "|")
    $prefix = if ($dateInfo.count -ge 10) { "pit_futility" } else { "pit_futility_pending" }
    $RunId = "${prefix}_$($identityHash.Substring(0, 12))"
}
if (-not $PlanPath) { $PlanPath = Join-Path $ArtifactRoot "$RunId.plan.json" }
if (-not $ResultPath) { $ResultPath = Join-Path $ArtifactRoot "$RunId.result.json" }
if (-not $ManifestPath) { $ManifestPath = Join-Path $ArtifactRoot "$RunId.manifest.json" }
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.launch.json"
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$ResultPath = [System.IO.Path]::GetFullPath($ResultPath)
$ManifestPath = [System.IO.Path]::GetFullPath($ManifestPath)
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)

function Get-ExistingCheckpoint {
    if (-not (Test-Path -LiteralPath $ManifestPath)) { return $null }
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if (
        [string]$manifest.schema -ne "pit_futility_visible_manifest_v1" -or
        [string]$manifest.run_id -ne $RunId -or
        $manifest.final -ne $true -or
        [int]$manifest.checkpoint_dates_read -ne 10 -or
        $manifest.deterministic_repeats_match -ne $true
    ) {
        throw "Existing PIT futility manifest is not a final deterministic 10-date checkpoint."
    }
    if (
        [string]$manifest.plan_path -ne $PlanPath -or
        [string]$manifest.result_path -ne $ResultPath -or
        -not (Test-Path -LiteralPath $PlanPath) -or
        -not (Test-Path -LiteralPath $ResultPath)
    ) {
        throw "Existing PIT futility manifest paths are missing or mismatched."
    }
    if (
        [string]$manifest.plan_file_sha256 -ne (Get-FileSha256 -Path $PlanPath) -or
        [string]$manifest.result_file_sha256 -ne (Get-FileSha256 -Path $ResultPath)
    ) {
        throw "Existing PIT futility artifact hash mismatch."
    }
    $plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    $result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    if (
        [string]$manifest.plan_hash -ne [string]$plan.plan_hash -or
        [string]$manifest.plan_hash -ne [string]$result.plan_hash -or
        [string]$manifest.deterministic_result_hash -ne [string]$result.deterministic_result_hash -or
        [string]$manifest.verdict -ne [string]$result.verdict -or
        [int]$result.checkpoint_dates_read -ne 10 -or
        $result.deterministic_repeats_match -ne $true
    ) {
        throw "Existing PIT futility manifest does not match its plan/result artifacts."
    }
    if (
        $manifest.returns_read -ne $false -or
        $manifest.pnl_computed -ne $false -or
        $manifest.oos_metrics_computed -ne $false -or
        $manifest.network_access -ne $false -or
        $manifest.grid_search -ne $false -or
        $manifest.retune -ne $false -or
        $result.returns_read -ne $false -or
        $result.pnl_computed -ne $false -or
        $result.oos_metrics_computed -ne $false -or
        $result.network_access -ne $false -or
        $result.grid_search -ne $false -or
        $result.retune -ne $false
    ) {
        throw "Existing PIT futility checkpoint violated embargo guards."
    }
    if ([string]$manifest.verdict -notin @("FUTILE_CLOSE_BRANCH_BEFORE_TRAIN", "CONTINUE_TO_20_DATE_TRAIN_GATE")) {
        throw "Existing PIT futility checkpoint has an unsupported verdict."
    }
    return $manifest
}

function Get-GateStatus {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ status = "MISSING"; run_id = $null }
    }
    $gate = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $status = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
    return [ordered]@{ status = $status; run_id = [string]$gate.run_id }
}

function Get-ApprovedDeadline {
    if (-not $ApprovedNotLaterThan) {
        return [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec)
    }
    $parsed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse(
        $ApprovedNotLaterThan,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AllowWhiteSpaces,
        [ref]$parsed
    )) {
        throw "ApprovedNotLaterThan is not a valid timestamp: $ApprovedNotLaterThan"
    }
    return $parsed
}

function Get-RemainingRuntimeSec {
    param(
        [Parameter(Mandatory)][datetime]$StartedAt,
        [Parameter(Mandatory)][DateTimeOffset]$Deadline
    )
    $byElapsed = $MaxRuntimeSec - [int][Math]::Floor(((Get-Date) - $StartedAt).TotalSeconds)
    $byDeadline = [int][Math]::Floor(($Deadline - [DateTimeOffset]::Now).TotalSeconds)
    $remaining = [Math]::Min($byElapsed, $byDeadline)
    if ($remaining -le 0) { throw "PIT futility runtime budget exhausted." }
    return $remaining
}

function Update-RunGate {
    param(
        [Parameter(Mandatory)][ValidateSet("RUNNING", "READY_FOR_POSTPROCESS", "STOPPED_INCOMPLETE")][string]$Status,
        [bool]$Final = $false,
        [int]$Errors = 0,
        [string]$StopReason = "",
        [string]$Failure = "",
        [string]$Verdict = "",
        [string]$PlanHash = "",
        [string]$ResultHash = "",
        [int]$CandidateEvents = 0
    )
    $now = (Get-Date).ToString("o")
    $decision = switch ($Status) {
        "RUNNING" { "PIT_FUTILITY_RUNNING" }
        "STOPPED_INCOMPLETE" { "PIT_FUTILITY_STOPPED_INCOMPLETE" }
        default {
            if ($Verdict -eq "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN") { "PIT_FUTILITY_BRANCH_CLOSED" }
            else { "PIT_FUTILITY_CONTINUE_TRAIN_ACCRUAL" }
        }
    }
    $nextStep = switch ($decision) {
        "PIT_FUTILITY_BRANCH_CLOSED" { "Bank the hypothesis without OOS or retune." }
        "PIT_FUTILITY_CONTINUE_TRAIN_ACCRUAL" { "Wait for the next approved quality-certified PIT date until the 20-date train gate." }
        "PIT_FUTILITY_STOPPED_INCOMPLETE" { "Resolve or visibly rerun this same hash-bound futility checkpoint before continuing." }
        default { "Wait for the visible embargo-safe futility worker to finish." }
    }
    $started = if ($script:StartedAt) { $script:StartedAt.ToString("o") } else { $now }
    $estimated = if ($script:Deadline) { $script:Deadline.ToString("o") } else { $null }
    $document = [ordered]@{
        schema = "active_run_gate_v2"
        project = "trading_mvp"
        run_id = $RunId
        status = $Status
        gate_status = $Status
        next_goal_decision = $decision
        next_goal_reason = $(if ($Failure) { $Failure } else { $nextStep })
        final = $Final
        primary_output_complete = ($Final -and (Test-Path -LiteralPath $ResultPath))
        expected_outputs_complete = ($Final -and (Test-Path -LiteralPath $PlanPath) -and (Test-Path -LiteralPath $ResultPath) -and (Test-Path -LiteralPath $ManifestPath))
        expected_outputs = [ordered]@{
            plan = $PlanPath
            result = $ResultPath
            manifest = $ManifestPath
        }
        updated_at = $now
        started_at = $started
        requested_duration_sec = $MaxRuntimeSec
        estimated_finish = $estimated
        actual_duration_sec = $(
            if ($Status -ne "RUNNING" -and $script:StartedAt) {
                [Math]::Round(((Get-Date) - $script:StartedAt).TotalSeconds, 3)
            } else { $null }
        )
        completed_cycles = $(if ($Final) { 2 } else { 0 })
        total_cycles = 2
        remaining_cycles = $(if ($Final) { 0 } else { 2 })
        rows = $CandidateEvents
        errors = $Errors
        monitor_pid = $(if ($Status -eq "RUNNING") { $PID } else { $null })
        process_ids = $(if ($Status -eq "RUNNING") { @($PID) } else { @() })
        output = [ordered]@{ path = $ResultPath; kind = "file" }
        manifest_path = $ManifestPath
        stop_reason = $StopReason
        plan_hash = $(if ($PlanHash) { $PlanHash } else { $null })
        deterministic_result_hash = $(if ($ResultHash) { $ResultHash } else { $null })
        replay_allowed = $false
        requires_explicit_user_approval_for_actual_collect = $false
        locks = @("pit_futility_artifacts", "active_run_gate")
        owner_output_prefix = $ArtifactRoot
        parallel_safe_actions = @("static_analysis", "unit_tests_on_immutable_fixtures")
        forbidden_overlapping_actions = @("collector", "probe", "postprocess", "grid", "oos", "live")
        next_step_after_ready = $nextStep
    }
    Write-JsonAtomic -Path $GatePath -Value $document
    Write-JsonAtomic -Path $CurrentRunPath -Value $document
}

function Invoke-RunMvpChild {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvpPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "run_mvp child failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Write-Stage {
    param([int]$Stage, [int]$Total, [string]$Message, [datetime]$StartedAt)
    $elapsed = [Math]::Round(((Get-Date) - $StartedAt).TotalSeconds, 1)
    Write-Host "[$Stage/$Total] $Message | elapsed=${elapsed}s" -ForegroundColor Cyan
}

$existingCheckpoint = Get-ExistingCheckpoint
if ($existingCheckpoint -and $dateInfo.count -lt 10) {
    throw "Quality ledger has fewer than ten dates but a futility checkpoint already exists."
}
$checkpointCompleted = ($null -ne $existingCheckpoint)
$checkpointVerdict = if ($existingCheckpoint) { [string]$existingCheckpoint.verdict } else { $null }
$checkpointReady = (-not $checkpointCompleted -and $dateInfo.count -ge 10 -and $dateInfo.count -lt 20)
$nextPlanAction = if ($dateInfo.count -gt 20) {
    "fail_closed_accepted_dates_exceed_train_gate"
} elseif ($checkpointCompleted) {
    if ($checkpointVerdict -eq "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN") {
        "branch_closed_before_train"
    } elseif ($dateInfo.count -lt 20) {
        "wait_for_next_quality_date"
    } else {
        "run_20_date_train_feasibility"
    }
} elseif ($dateInfo.count -lt 10) {
    "wait_for_tenth_quality_date"
} elseif ($dateInfo.count -ge 20) {
    "fail_closed_missed_ten_date_futility"
} else {
    "run_visible_10_date_futility"
}
$launchPlan = [ordered]@{
    schema = "pit_futility_visible_launch_v1"
    decision = "PLAN_ONLY"
    stage = "pit_10_date_futility"
    run_id = $RunId
    visible_terminal = $true
    checkpoint_ready = $checkpointReady
    checkpoint_completed = $checkpointCompleted
    checkpoint_verdict = $checkpointVerdict
    accepted_distinct_dates = [int]$dateInfo.count
    accepted_date_values = @($dateInfo.dates)
    sealed_checkpoint_dates = @($dateInfo.dates | Select-Object -First 10)
    deterministic_repeats = 2
    plan_path = $PlanPath
    result_path = $ResultPath
    manifest_path = $ManifestPath
    gate_path = $GatePath
    current_run_path = $CurrentRunPath
    launch_record_path = $LaunchRecordPath
    max_runtime_sec = $MaxRuntimeSec
    next_allowed_action = $nextPlanAction
    network_access = $false
    returns_read = $false
    pnl_computed = $false
    oos_evaluation = $false
    grid_search = $false
    retune = $false
    execution_probe = $false
    paper_forward = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
}

if ($PlanOnly) {
    $launchPlan | ConvertTo-Json -Depth 20
    exit 0
}

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Visible worker requires an ownership token and launch record."
    }
    $ownership = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if (
        [string]$ownership.run_id -ne $RunId -or
        [string]$ownership.plan_path -ne $PlanPath -or
        [string]$ownership.result_path -ne $ResultPath -or
        [string]$ownership.manifest_path -ne $ManifestPath
    ) {
        throw "Visible worker ownership record mismatch."
    }
    if ([string]$ownership.worker_token_sha256 -ne (Get-TextSha256 -Value $WorkerToken)) {
        throw "Visible worker ownership token mismatch."
    }
} else {
    $gate = Get-GateStatus -Path $GatePath
    if ($gate.status -eq "RUNNING") {
        throw "Visible PIT futility blocked by active gate status=RUNNING, run_id=$($gate.run_id)"
    }
    if ($gate.status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before starting PIT futility."
    }
    if ($existingCheckpoint) {
        Get-Content -LiteralPath $ManifestPath -Raw
        exit 0
    }
    if (-not $checkpointReady) {
        throw "PIT futility checkpoint is not due: accepted_dates=$($dateInfo.count), next=$nextPlanAction."
    }
    foreach ($output in @($PlanPath, $ResultPath)) {
        if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite immutable output: $output" }
    }
    $approvedDeadline = Get-ApprovedDeadline
    $runtimeDeadline = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec)
    $deadline = if ($approvedDeadline -lt $runtimeDeadline) { $approvedDeadline } else { $runtimeDeadline }
    if ($deadline -le [DateTimeOffset]::Now) { throw "Approved deadline has already passed." }
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $token = [System.Guid]::NewGuid().ToString("N")
    $launchPlan.worker_token_sha256 = Get-TextSha256 -Value $token
    $launchPlan.status = "LAUNCHING"
    $launchPlan.launcher_pid = $PID
    $launchPlan.started_at = (Get-Date).ToString("o")
    $launchPlan.approved_not_later_than = $deadline.ToString("o")
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    $args = @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Worker", "-WorkerToken", "`"$token`"",
        "-RunId", "`"$RunId`"",
        "-ArtifactRoot", "`"$ArtifactRoot`"",
        "-QualityLedgerPath", "`"$QualityLedgerPath`"",
        "-HypothesisBankPath", "`"$HypothesisBankPath`"",
        "-Hypothesis", "`"$Hypothesis`"",
        "-PlanPath", "`"$PlanPath`"",
        "-ResultPath", "`"$ResultPath`"",
        "-ManifestPath", "`"$ManifestPath`"",
        "-GatePath", "`"$GatePath`"",
        "-CurrentRunPath", "`"$CurrentRunPath`"",
        "-LaunchRecordPath", "`"$LaunchRecordPath`"",
        "-MaxRuntimeSec", "$MaxRuntimeSec",
        "-HoldOpenSec", "$HoldOpenSec",
        "-ApprovedNotLaterThan", "`"$($deadline.ToString('o'))`""
    )
    $script:StartedAt = Get-Date
    $script:Deadline = $deadline
    $process = Start-Process -FilePath $pwsh -ArgumentList $args -WindowStyle Normal -PassThru
    $launchPlan.worker_pid = $process.Id
    $launchPlan.status = "RUNNING"
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    Write-Host "Visible PIT futility worker opened. PID=$($process.Id)" -ForegroundColor Green
    Write-Host "Hard deadline: $($deadline.ToString('o'))"
    $waitMs = ([int][Math]::Ceiling(($deadline - [DateTimeOffset]::Now).TotalMilliseconds)) + (($HoldOpenSec + 30) * 1000)
    if ($waitMs -lt 1000 -or -not $process.WaitForExit($waitMs)) {
        try { $process.Kill($true) } catch { }
        try { $process.WaitForExit(5000) } catch { }
        try {
            Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "pit_futility_timeout" -Failure "Visible PIT futility worker exceeded its hard deadline."
        } catch {
            Write-Warning "Could not close timed-out PIT futility gate: $($_.Exception.Message)"
        }
        throw "Visible PIT futility worker exceeded its hard deadline."
    }
    if ($process.ExitCode -ne 0) {
        $gateAlreadyClosed = $false
        try {
            $workerGate = Get-GateStatus -Path $GatePath
            $gateAlreadyClosed = ($workerGate.run_id -eq $RunId -and $workerGate.status -eq "STOPPED_INCOMPLETE")
        } catch { }
        if (-not $gateAlreadyClosed) {
            try {
                Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "worker_exit_nonzero" -Failure "Visible PIT futility worker exited with code $($process.ExitCode)."
            } catch {
                Write-Warning "Could not close nonzero PIT futility gate: $($_.Exception.Message)"
            }
        }
        throw "Visible PIT futility worker exited with code $($process.ExitCode)"
    }
    $launchPlan.status = "COMPLETED"
    $launchPlan.worker_exit_code = 0
    $launchPlan.completed_at = (Get-Date).ToString("o")
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    Get-Content -LiteralPath $ManifestPath -Raw
    exit 0
}

$startedAt = Get-Date
$approvedDeadline = Get-ApprovedDeadline
$runtimeDeadline = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec)
$deadline = if ($approvedDeadline -lt $runtimeDeadline) { $approvedDeadline } else { $runtimeDeadline }
$script:StartedAt = $startedAt
$script:Deadline = $deadline
try { $host.UI.RawUI.WindowTitle = "trading_mvp PIT 10-date futility - $RunId" } catch { }
Write-Host "trading_mvp PIT: visible embargo-safe 10-date futility" -ForegroundColor Yellow
Write-Host "run_id=$RunId"
Write-Host "hard_deadline=$($deadline.ToString('o'))"
Write-Host "quality_ledger=$QualityLedgerPath"

try {
    if ($dateInfo.count -lt 10) { throw "PIT futility requires 10 accepted dates; observed=$($dateInfo.count)." }
    if ($dateInfo.count -ge 20) { throw "PIT futility checkpoint was missed; 20-date train gate is already due." }
    Update-RunGate -Status RUNNING -StopReason "pit_futility_started"

    Write-Stage -Stage 1 -Total 3 -Message "Sealing earliest ten accepted PIT dates" -StartedAt $startedAt
    $remaining = [Math]::Min(1200, (Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline))
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-pit-futility-plan",
        "-RunId", $RunId,
        "-ActiveRunGatePath", $GatePath,
        "-QualityLedgerPath", $QualityLedgerPath,
        "-HypothesisBankPath", $HypothesisBankPath,
        "-Hypothesis", $Hypothesis,
        "-OutputPath", $PlanPath,
        "-MaxRuntimeSec", $remaining
    )
    $plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    $planHash = [string]$plan.plan_hash
    if (
        -not $planHash -or
        [string]$plan.mode -ne "PlanOnly" -or
        @($plan.sealed_input.selected_dates).Count -ne 10 -or
        $plan.forward_market_rows_read -ne $false -or
        $plan.returns_read -ne $false -or
        $plan.pnl_computed -ne $false
    ) {
        throw "Generated futility plan violated the sealed 10-date embargo-safe contract."
    }

    Write-Stage -Stage 2 -Total 3 -Message "Evaluating optimistic event-frequency upper bounds" -StartedAt $startedAt
    $remaining = Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-pit-futility-evaluate",
        "-RunId", $RunId,
        "-ActiveRunGatePath", $GatePath,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanHash", $planHash,
        "-OutputPath", $ResultPath,
        "-MaxRuntimeSec", $remaining
    )
    $result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    if ([string]$result.verdict -notin @("FUTILE_CLOSE_BRANCH_BEFORE_TRAIN", "CONTINUE_TO_20_DATE_TRAIN_GATE")) {
        throw "Unexpected PIT futility verdict: $($result.verdict)"
    }
    if (
        [string]$result.plan_hash -ne $planHash -or
        [int]$result.checkpoint_dates_read -ne 10 -or
        $result.deterministic_repeats_match -ne $true -or
        $result.returns_read -ne $false -or
        $result.pnl_computed -ne $false -or
        $result.oos_metrics_computed -ne $false -or
        $result.network_access -ne $false -or
        $result.grid_search -ne $false -or
        $result.retune -ne $false
    ) {
        throw "PIT futility result violated determinism or embargo guards."
    }

    Write-Stage -Stage 3 -Total 3 -Message "Writing immutable manifest and closing owned gate" -StartedAt $startedAt
    $manifest = [ordered]@{
        schema = "pit_futility_visible_manifest_v1"
        run_id = $RunId
        project = "trading_mvp"
        final = $true
        created_at = (Get-Date).ToString("o")
        stop_condition = "completed_embargo_safe_10_date_futility"
        completed_cycles = 2
        cycles = 2
        rows = [int]$result.candidate_events
        errors = 0
        hypothesis_id = $Hypothesis
        plan_path = $PlanPath
        plan_hash = $planHash
        plan_file_sha256 = Get-FileSha256 -Path $PlanPath
        result_path = $ResultPath
        result_file_sha256 = Get-FileSha256 -Path $ResultPath
        deterministic_repeats = [int]$result.deterministic_repeats
        deterministic_repeats_match = [bool]$result.deterministic_repeats_match
        deterministic_result_hash = [string]$result.deterministic_result_hash
        verdict = [string]$result.verdict
        rejection_reasons = @($result.rejection_reasons)
        checkpoint_dates_read = [int]$result.checkpoint_dates_read
        checkpoint_date_values = @($result.checkpoint_date_values)
        candidate_events = [int]$result.candidate_events
        valid_events = [int]$result.valid_events
        returns_read = $false
        pnl_computed = $false
        oos_metrics_computed = $false
        network_access = $false
        grid_search = $false
        retune = $false
        execution_probe_allowed = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        next_allowed_action = [string]$result.next_allowed_action
        next_allowed_command = [string]$result.next_allowed_command
        runtime_sec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
    }
    Write-JsonAtomic -Path $ManifestPath -Value $manifest
    Update-RunGate `
        -Status READY_FOR_POSTPROCESS `
        -Final $true `
        -StopReason $manifest.stop_condition `
        -Verdict $manifest.verdict `
        -PlanHash $planHash `
        -ResultHash $manifest.deterministic_result_hash `
        -CandidateEvents $manifest.candidate_events
    Write-Host "VERDICT=$($manifest.verdict)" -ForegroundColor Green
    Write-Host "result_hash=$($manifest.deterministic_result_hash)"
    Write-Host "manifest=$ManifestPath"
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 0
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    $failurePath = Join-Path $ArtifactRoot "$RunId.failure.json"
    Write-JsonAtomic -Path $failurePath -Value ([ordered]@{
        schema = "pit_futility_visible_failure_v1"
        run_id = $RunId
        final = $false
        created_at = (Get-Date).ToString("o")
        error = $message
        plan_path = $PlanPath
        result_path = $ResultPath
        manifest_path = $ManifestPath
        returns_read = $false
        pnl_computed = $false
        oos_metrics_computed = $false
        network_access = $false
        grid_search = $false
        retune = $false
    })
    try {
        Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "pit_futility_failed" -Failure $message
    } catch {
        Write-Warning "Could not close failed PIT futility gate: $($_.Exception.Message)"
    }
    Write-Error $message
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 1
}
