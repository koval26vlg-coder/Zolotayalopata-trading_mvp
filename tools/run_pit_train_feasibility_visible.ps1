[CmdletBinding()]
param(
    [string]$RunId = "",
    [string]$ArtifactRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\pit-train-feasibility",
    [string]$QualityLedgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl",
    [string]$HypothesisBankPath = "",
    [string]$Hypothesis = "pit_universe_membership_drift_reversion_v1",
    [string]$PlanPath = "",
    [string]$FeasibilityPath = "",
    [string]$RepeatFeasibilityPath = "",
    [string]$OosSchedulePath = "",
    [string]$OosOutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2",
    [string]$OosScheduleStartDate = "",
    [ValidateRange(1, 14)][int]$OosScheduleNights = 14,
    [string]$OosScheduleStartLocal = "23:00",
    [ValidateRange(1, 10800)][int]$OosSegmentDurationSec = 1200,
    [ValidateRange(1, 10800)][int]$OosIntervalSec = 300,
    [string]$ManifestPath = "",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [string]$ApprovedNotLaterThan = "",
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
$CanonicalGoalPath = Join-Path $ProjectRoot "docs\plans\2026-07-14-trading-mvp-canonical-goal-v3.md"
$CanonicalGoalSha256 = "aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c"
if (-not $HypothesisBankPath) {
    $HypothesisBankPath = Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
}
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json"
}
if (-not $RunId) {
    $RunId = "pit_train_feasibility_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
if (-not $PlanPath) {
    $PlanPath = Join-Path $ArtifactRoot "$RunId.input-plan.json"
}
if (-not $FeasibilityPath) {
    $FeasibilityPath = Join-Path $ArtifactRoot "$RunId.feasibility.json"
}
if (-not $RepeatFeasibilityPath) {
    $RepeatFeasibilityPath = Join-Path $ArtifactRoot "$RunId.feasibility.repeat.json"
}
if (-not $OosSchedulePath) {
    $OosSchedulePath = Join-Path $ArtifactRoot "$RunId.oos-accrual-plan.json"
}
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $ArtifactRoot "$RunId.manifest.json"
}
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\$RunId.launch.json"
}
$GatePaths = @($GatePath, $CurrentRunPath) | Select-Object -Unique
$script:StartedAt = $null
$script:Deadline = $null

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string]$Name,
        $Value
    )
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temporary -Encoding utf8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Assert-ArtifactPath {
    param([Parameter(Mandatory)][string]$Path)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($ArtifactRoot).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Feasibility artifacts must stay under $ArtifactRoot, observed: $fullPath"
    }
}

function Get-GateStatus {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Run gate is missing: $Path"
    }
    $document = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $status = if ($document.gate_status) { [string]$document.gate_status } else { [string]$document.status }
    return [pscustomobject]@{ status = $status; run_id = [string]$document.run_id }
}

function Get-NextDecision {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") { return "PIT_TRAIN_FEASIBILITY_RUNNING" }
    if ($Status -eq "STOPPED_INCOMPLETE") { return "PIT_TRAIN_FEASIBILITY_STOPPED_INCOMPLETE" }
    if ($Verdict -eq "FEASIBLE_FOR_OOS") { return "PIT_OOS_ACCRUAL_PLAN_READY_FOR_APPROVAL" }
    return "PIT_TRAIN_INFEASIBLE_ON_CURRENT_DATA"
}

function Get-NextStep {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") {
        return "Wait for the visible train-only feasibility worker; do not read OOS or launch another run."
    }
    if ($Status -eq "STOPPED_INCOMPLETE") {
        return "Inspect the visible failure and preserve partial artifacts; do not run OOS."
    }
    if ($Verdict -eq "FEASIBLE_FOR_OOS") {
        return "Review and explicitly approve the immutable OOS-accrual night schedule PlanOnly; no collection starts before that approval."
    }
    return "Bank the hypothesis with its data requirements and do not run OOS or retune it."
}

function Get-NextReason {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") {
        return "Owned visible train-only feasibility is running under the frozen PIT-universe hypothesis."
    }
    if ($Status -eq "STOPPED_INCOMPLETE") {
        return "Train-only feasibility did not complete; partial artifacts are not accepted evidence."
    }
    if ($Verdict -eq "FEASIBLE_FOR_OOS") {
        return "Frozen train-only feasibility passed and produced an approval-ready OOS-accrual PlanOnly without reading OOS returns."
    }
    return "Frozen train-only feasibility rejected the branch on current data without reading OOS returns."
}

function Update-RunGate {
    param(
        [Parameter(Mandatory)][ValidateSet("RUNNING", "READY_FOR_POSTPROCESS", "STOPPED_INCOMPLETE")][string]$Status,
        [bool]$Final = $false,
        [int]$Errors = 0,
        [int]$CandidateEvents = 0,
        [string]$StopReason = "",
        [string]$Verdict = "",
        [string]$PlanHash = "",
        [string]$ResultHash = "",
        [string]$OosPlanHash = "",
        [string]$Failure = ""
    )
    $now = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffffffK")
    foreach ($path in $GatePaths) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Run gate is missing: $path"
        }
        $document = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $fields = [ordered]@{
            project = "trading_mvp"
            run_id = $RunId
            status = $Status
            gate_status = $Status
            final = $Final
            primary_output_complete = ($Final -and (Test-Path -LiteralPath $FeasibilityPath))
            expected_outputs_complete = (
                $Final -and
                (Test-Path -LiteralPath $PlanPath) -and
                (Test-Path -LiteralPath $RepeatFeasibilityPath) -and
                (Test-Path -LiteralPath $ManifestPath) -and
                ($Verdict -ne "FEASIBLE_FOR_OOS" -or (Test-Path -LiteralPath $OosSchedulePath))
            )
            expected_outputs = [ordered]@{
                input_plan = $PlanPath
                feasibility = $FeasibilityPath
                deterministic_repeat = $RepeatFeasibilityPath
                oos_accrual_planonly = $OosSchedulePath
                manifest = $ManifestPath
            }
            updated_at = $now
            started_at = $(if ($script:StartedAt) { $script:StartedAt.ToString("o") } else { $document.started_at })
            requested_duration_sec = $MaxRuntimeSec
            estimated_finish = $(if ($script:Deadline) { $script:Deadline.ToString("o") } else { $document.estimated_finish })
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
            collector_pid = $null
            process_ids = $(if ($Status -eq "RUNNING") { @($PID) } else { @() })
    launch_record_path = $LaunchRecordPath
            output = [ordered]@{ path = $FeasibilityPath; type = "pit_train_only_feasibility" }
            output_path = $FeasibilityPath
            plan_path = $PlanPath
            plan_hash = $PlanHash
            deterministic_repeat_path = $RepeatFeasibilityPath
            manifest_path = $ManifestPath
            feasibility_result_hash = $ResultHash
            oos_schedule_path = $(if ($Verdict -eq "FEASIBLE_FOR_OOS") { $OosSchedulePath } else { $null })
            oos_schedule_plan_hash = $OosPlanHash
            verdict = $Verdict
            stop_reason = $StopReason
            failure = $Failure
            replay_allowed = $false
            grid_allowed = $false
            backtest_allowed = $false
            evaluation_allowed = $false
            execution_probe_allowed = $false
            paper_forward_allowed = $false
            live_orders = $false
            api_keys = $false
            leverage_or_margin = $false
            next_goal_decision = Get-NextDecision -Status $Status -Verdict $Verdict
            next_goal_reason = Get-NextReason -Status $Status -Verdict $Verdict
            next_step_after_ready = Get-NextStep -Status $Status -Verdict $Verdict
        }
        foreach ($entry in $fields.GetEnumerator()) {
            Set-ObjectProperty -Object $document -Name $entry.Key -Value $entry.Value
        }
        Write-JsonAtomic -Path $path -Value $document
    }
}

function Invoke-RunMvpChild {
    param([Parameter(Mandatory)][object[]]$Arguments)
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    & $pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvp @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "run_mvp.ps1 failed with exit code $LASTEXITCODE"
    }
}

function Get-ApprovedDeadline {
    if (-not $ApprovedNotLaterThan) {
        return [DateTimeOffset](Get-Date).AddSeconds($MaxRuntimeSec)
    }
    return [DateTimeOffset]::Parse(
        $ApprovedNotLaterThan,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
}

function Get-RemainingRuntimeSec {
    param([Parameter(Mandatory)][datetime]$StartedAt, [Parameter(Mandatory)][DateTimeOffset]$Deadline)
    $runtimeRemaining = $MaxRuntimeSec - [int]((Get-Date) - $StartedAt).TotalSeconds
    $deadlineRemaining = [int][Math]::Floor(($Deadline - [DateTimeOffset]::Now).TotalSeconds)
    $remaining = [Math]::Min($runtimeRemaining, $deadlineRemaining)
    if ($remaining -lt 1) { throw "Visible feasibility run reached its hard deadline." }
    return $remaining
}

function Write-Stage {
    param([int]$Stage, [int]$Total, [string]$Message, [datetime]$StartedAt)
    $elapsed = [int]((Get-Date) - $StartedAt).TotalSeconds
    $remaining = [Math]::Max(0, $MaxRuntimeSec - $elapsed)
    Write-Host "[$Stage/$Total] $Message | elapsed=${elapsed}s | max_remaining=${remaining}s" -ForegroundColor Cyan
}

foreach ($path in @($PlanPath, $FeasibilityPath, $RepeatFeasibilityPath, $OosSchedulePath, $ManifestPath)) {
    Assert-ArtifactPath -Path $path
}
foreach ($required in @($QualityLedgerPath, $HypothesisBankPath, $CanonicalGoalPath, $RunMvp)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required input is missing: $required" }
}
if ((Get-FileHash -LiteralPath $CanonicalGoalPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $CanonicalGoalSha256) {
    throw "Canonical goal SHA-256 mismatch."
}

$launchPlan = [ordered]@{
    schema = "pit_train_feasibility_visible_launch_v1"
    decision = $(if ($PlanOnly) { "PLAN_ONLY" } elseif ($Worker) { "WORKER" } else { "VISIBLE_LAUNCH" })
    stage = "train_feasibility"
    run_id = $RunId
    artifact_root = [System.IO.Path]::GetFullPath($ArtifactRoot)
    quality_ledger_path = [System.IO.Path]::GetFullPath($QualityLedgerPath)
    hypothesis_bank_path = [System.IO.Path]::GetFullPath($HypothesisBankPath)
    hypothesis_id = $Hypothesis
    canonical_goal_path = [System.IO.Path]::GetFullPath($CanonicalGoalPath)
    canonical_goal_sha256 = $CanonicalGoalSha256
    plan_path = [System.IO.Path]::GetFullPath($PlanPath)
    feasibility_path = [System.IO.Path]::GetFullPath($FeasibilityPath)
    repeat_feasibility_path = [System.IO.Path]::GetFullPath($RepeatFeasibilityPath)
    oos_schedule_path = [System.IO.Path]::GetFullPath($OosSchedulePath)
    oos_schedule_stage = "oos_accrual"
    oos_output_root = [System.IO.Path]::GetFullPath($OosOutputRoot)
    oos_schedule_start_date = $OosScheduleStartDate
    oos_schedule_nights = $OosScheduleNights
    oos_schedule_start_local = $OosScheduleStartLocal
    oos_segment_duration_sec = $OosSegmentDurationSec
    oos_interval_sec = $OosIntervalSec
    manifest_path = [System.IO.Path]::GetFullPath($ManifestPath)
    max_runtime_sec = $MaxRuntimeSec
    visible_terminal = $true
    deterministic_repeats = 2
    network_access = $false
    oos_returns_read = $false
    grid_search = $false
    retune = $false
    execution_probe = $false
    paper_forward = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
}
if ($PlanOnly) {
    $launchPlan | ConvertTo-Json -Depth 12
    exit 0
}

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Visible worker requires an ownership token and launch record."
    }
    $ownership = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if (
        [string]$ownership.run_id -ne $RunId -or
        [string]$ownership.plan_path -ne [System.IO.Path]::GetFullPath($PlanPath) -or
        [string]$ownership.feasibility_path -ne [System.IO.Path]::GetFullPath($FeasibilityPath) -or
        [string]$ownership.repeat_feasibility_path -ne [System.IO.Path]::GetFullPath($RepeatFeasibilityPath) -or
        [string]$ownership.oos_schedule_path -ne [System.IO.Path]::GetFullPath($OosSchedulePath)
    ) {
        throw "Visible worker ownership record mismatch."
    }
    if ([string]$ownership.worker_token_sha256 -ne (Get-TextSha256 -Value $WorkerToken)) {
        throw "Visible worker ownership token mismatch."
    }
} else {
    $gate = Get-GateStatus -Path $GatePath
    if ($gate.status -eq "RUNNING") {
        throw "Visible feasibility blocked by active gate status=RUNNING, run_id=$($gate.run_id)"
    }
    if ($gate.status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before starting train feasibility."
    }
    foreach ($output in @($PlanPath, $FeasibilityPath, $RepeatFeasibilityPath, $OosSchedulePath, $ManifestPath)) {
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
        "-FeasibilityPath", "`"$FeasibilityPath`"",
        "-RepeatFeasibilityPath", "`"$RepeatFeasibilityPath`"",
        "-OosSchedulePath", "`"$OosSchedulePath`"",
        "-OosOutputRoot", "`"$OosOutputRoot`"",
        "-OosScheduleStartDate", "`"$OosScheduleStartDate`"",
        "-OosScheduleNights", "$OosScheduleNights",
        "-OosScheduleStartLocal", "`"$OosScheduleStartLocal`"",
        "-OosSegmentDurationSec", "$OosSegmentDurationSec",
        "-OosIntervalSec", "$OosIntervalSec",
        "-ManifestPath", "`"$ManifestPath`"",
        "-GatePath", "`"$GatePath`"",
        "-CurrentRunPath", "`"$CurrentRunPath`"",
        "-LaunchRecordPath", "`"$LaunchRecordPath`"",
        "-MaxRuntimeSec", "$MaxRuntimeSec",
        "-HoldOpenSec", "$HoldOpenSec",
        "-ApprovedNotLaterThan", "`"$($deadline.ToString('o'))`""
    )
    $process = Start-Process -FilePath $pwsh -ArgumentList $args -WindowStyle Normal -PassThru
    $launchPlan.worker_pid = $process.Id
    $launchPlan.status = "RUNNING"
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    Write-Host "Visible PIT train feasibility opened. PID=$($process.Id)" -ForegroundColor Green
    Write-Host "Hard deadline: $($deadline.ToString('o'))"
    $waitMs = ([int][Math]::Ceiling(($deadline - [DateTimeOffset]::Now).TotalMilliseconds)) + (($HoldOpenSec + 30) * 1000)
    if ($waitMs -lt 1000 -or -not $process.WaitForExit($waitMs)) {
        try { $process.Kill($true) } catch { }
        try { $process.WaitForExit(5000) } catch { }
        try {
            Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "train_feasibility_timeout" -Failure "Visible feasibility worker exceeded its hard deadline."
        } catch {
            Write-Warning "Could not close the timed-out feasibility gate: $($_.Exception.Message)"
        }
        throw "Visible feasibility worker exceeded its hard deadline."
    }
    if ($process.ExitCode -ne 0) {
        $gateAlreadyClosed = $false
        try {
            $workerGate = Get-GateStatus -Path $GatePath
            $gateAlreadyClosed = ($workerGate.run_id -eq $RunId -and $workerGate.status -eq "STOPPED_INCOMPLETE")
        } catch { }
        if (-not $gateAlreadyClosed) {
            try {
                Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "worker_exit_nonzero" -Failure "Visible feasibility worker exited with code $($process.ExitCode)."
            } catch {
                Write-Warning "Could not close the nonzero feasibility gate: $($_.Exception.Message)"
            }
        }
        throw "Visible feasibility worker exited with code $($process.ExitCode)"
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
try { $host.UI.RawUI.WindowTitle = "trading_mvp PIT train feasibility - $RunId" } catch { }
Write-Host "trading_mvp PIT: visible train-only feasibility" -ForegroundColor Yellow
Write-Host "run_id=$RunId"
Write-Host "hard_deadline=$($deadline.ToString('o'))"
Write-Host "quality_ledger=$QualityLedgerPath"

try {
    Update-RunGate -Status RUNNING -StopReason "train_feasibility_started"

    Write-Stage -Stage 1 -Total 5 -Message "Building immutable train-only input plan" -StartedAt $startedAt
    $remaining = [Math]::Min(1200, (Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline))
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-pit-input-plan",
        "-RunId", $RunId,
        "-ActiveRunGatePath", $GatePath,
        "-QualityLedgerPath", $QualityLedgerPath,
        "-HypothesisBankPath", $HypothesisBankPath,
        "-Hypothesis", $Hypothesis,
        "-PitPlanStage", "train_feasibility",
        "-OutputPath", $PlanPath,
        "-MaxRuntimeSec", $remaining
    )
    $plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    $planHash = [string]$plan.plan_hash
    if (-not $planHash -or [string]$plan.sealed_input.plan_stage -ne "train_feasibility") {
        throw "Generated input plan is not a sealed train_feasibility plan."
    }
    if (@($plan.sealed_input.split.train_dates).Count -ne 20 -or @($plan.sealed_input.split.oos_dates).Count -ne 0) {
        throw "Train input plan must contain exactly 20 train dates and zero OOS dates."
    }
    if ($plan.oos_returns_read -ne $false) { throw "Input plan reports OOS access." }

    Write-Stage -Stage 2 -Total 5 -Message "Running frozen train-only feasibility" -StartedAt $startedAt
    $remaining = Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-pit-feasibility",
        "-RunId", $RunId,
        "-ActiveRunGatePath", $GatePath,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanHash", $planHash,
        "-OutputPath", $FeasibilityPath,
        "-MaxRuntimeSec", $remaining
    )
    $first = Get-Content -LiteralPath $FeasibilityPath -Raw | ConvertFrom-Json

    Write-Stage -Stage 3 -Total 5 -Message "Repeating feasibility for deterministic equality" -StartedAt $startedAt
    $remaining = Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline
    $firstBackupPath = "$FeasibilityPath.first.$PID.tmp"
    Move-Item -LiteralPath $FeasibilityPath -Destination $firstBackupPath
    try {
        # The sealed evaluator binds next_allowed_command to its output path, so both
        # deterministic passes must use the same canonical path.
        Invoke-RunMvpChild -Arguments @(
            "-Action", "fast-edge-pit-feasibility",
            "-RunId", $RunId,
            "-ActiveRunGatePath", $GatePath,
            "-PlanPath", $PlanPath,
            "-ExpectedPlanHash", $planHash,
            "-OutputPath", $FeasibilityPath,
            "-MaxRuntimeSec", $remaining
        )
        $repeat = Get-Content -LiteralPath $FeasibilityPath -Raw | ConvertFrom-Json
        Move-Item -LiteralPath $FeasibilityPath -Destination $RepeatFeasibilityPath
    } finally {
        if (Test-Path -LiteralPath $firstBackupPath) {
            Move-Item -LiteralPath $firstBackupPath -Destination $FeasibilityPath -Force
        }
    }
    if ([string]$first.deterministic_result_hash -ne [string]$repeat.deterministic_result_hash) {
        throw "Deterministic feasibility repeat mismatch."
    }
    if ([string]$first.verdict -ne [string]$repeat.verdict) {
        throw "Deterministic feasibility verdict mismatch."
    }
    if ([string]$first.verdict -notin @("FEASIBLE_FOR_OOS", "INFEASIBLE_ON_CURRENT_DATA")) {
        throw "Unexpected train feasibility verdict: $($first.verdict)"
    }
    foreach ($artifact in @($first, $repeat)) {
        if ([string]$artifact.plan_hash -ne $planHash -or [int]$artifact.train_dates_read -ne 20) {
            throw "Feasibility artifact is not bound to the 20-date train plan."
        }
        if ([int]$artifact.oos_dates_read -ne 0 -or $artifact.returns_read -ne $false -or $artifact.pnl_computed -ne $false) {
            throw "Feasibility artifact violated the OOS/returns/PnL embargo."
        }
        if ($artifact.network_access -ne $false -or $artifact.grid_search -ne $false -or $artifact.retune -ne $false) {
            throw "Feasibility artifact violated research-only execution guards."
        }
    }

    $oosSchedule = $null
    if ([string]$first.verdict -eq "FEASIBLE_FOR_OOS") {
        Write-Stage -Stage 4 -Total 5 -Message "Building immutable OOS-accrual schedule PlanOnly" -StartedAt $startedAt
        $lastTrainDate = @($plan.sealed_input.split.train_dates | Sort-Object | Select-Object -Last 1)[0]
        if (-not $lastTrainDate) { throw "Train plan does not expose its last accepted date." }
        $computedOosStart = ([datetime]::ParseExact(
            [string]$lastTrainDate,
            "yyyy-MM-dd",
            [System.Globalization.CultureInfo]::InvariantCulture
        )).AddDays(1).ToString("yyyy-MM-dd")
        $resolvedOosStart = if ($OosScheduleStartDate) { $OosScheduleStartDate } else { $computedOosStart }
        if ([datetime]::ParseExact(
            $resolvedOosStart,
            "yyyy-MM-dd",
            [System.Globalization.CultureInfo]::InvariantCulture
        ) -le [datetime]::ParseExact(
            [string]$lastTrainDate,
            "yyyy-MM-dd",
            [System.Globalization.CultureInfo]::InvariantCulture
        )) {
            throw "OOS schedule must start after the final train date."
        }
        $remaining = [Math]::Min(1200, (Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline))
        Invoke-RunMvpChild -Arguments @(
            "-Action", "fast-edge-night-schedule-plan",
            "-RunId", $RunId,
            "-ActiveRunGatePath", $GatePath,
            "-HypothesisBankPath", $HypothesisBankPath,
            "-Hypothesis", $Hypothesis,
            "-DataType", "PIT_UNIVERSE_V2_FORWARD",
            "-ScheduleStartDate", $resolvedOosStart,
            "-ScheduleNights", $OosScheduleNights,
            "-ScheduleStartLocal", $OosScheduleStartLocal,
            "-ScheduleCollectionStage", "oos_accrual",
            "-ScheduleSegmentDurationSec", $OosSegmentDurationSec,
            "-ScheduleIntervalSec", $OosIntervalSec,
            "-ScheduleOutputRoot", $OosOutputRoot,
            "-QualityLedgerPath", $QualityLedgerPath,
            "-TrainPlanPath", $PlanPath,
            "-FeasibilityPath", $FeasibilityPath,
            "-OutputPath", $OosSchedulePath,
            "-MaxRuntimeSec", $remaining
        )
        $oosSchedule = Get-Content -LiteralPath $OosSchedulePath -Raw | ConvertFrom-Json
        if (
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
            throw "Generated OOS schedule violated PlanOnly or embargo guards."
        }
        $oosStage = $oosSchedule.sealed_schedule.collection_stage
        if (
            [string]$oosStage.name -ne "oos_accrual" -or
            [int]$oosStage.initial_accepted_distinct_dates -ne 20 -or
            [int]$oosStage.stage_target_distinct_dates -ne 120 -or
            [string]$oosStage.upstream_train_feasibility.verdict -ne "FEASIBLE_FOR_OOS"
        ) {
            throw "Generated OOS schedule is not bound to the passed 20-date feasibility artifact."
        }
    } else {
        Write-Stage -Stage 4 -Total 5 -Message "Feasibility rejected; OOS PlanOnly remains absent" -StartedAt $startedAt
    }

    Write-Stage -Stage 5 -Total 5 -Message "Writing final manifest and closing gate" -StartedAt $startedAt
    $manifest = [ordered]@{
        schema = "pit_train_feasibility_manifest_v2"
        run_id = $RunId
        project = "trading_mvp"
        final = $true
        created_at = (Get-Date).ToString("o")
        stop_condition = $(
            if ($oosSchedule) { "completed_train_feasibility_and_oos_accrual_planonly" }
            else { "completed_two_deterministic_train_feasibility_runs" }
        )
        completed_cycles = 2
        cycles = 2
        rows = [int]$first.train_candidate_events
        errors = 0
        hypothesis_id = $Hypothesis
        canonical_goal_sha256 = $CanonicalGoalSha256
        plan_path = [System.IO.Path]::GetFullPath($PlanPath)
        plan_hash = $planHash
        plan_file_sha256 = (Get-FileHash -LiteralPath $PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
        feasibility_path = [System.IO.Path]::GetFullPath($FeasibilityPath)
        feasibility_file_sha256 = (Get-FileHash -LiteralPath $FeasibilityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        repeat_feasibility_path = [System.IO.Path]::GetFullPath($RepeatFeasibilityPath)
        repeat_feasibility_file_sha256 = (Get-FileHash -LiteralPath $RepeatFeasibilityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        deterministic_repeats = 2
        deterministic_repeats_match = $true
        deterministic_result_hash = [string]$first.deterministic_result_hash
        verdict = [string]$first.verdict
        rejection_reasons = @($first.rejection_reasons)
        train_dates_read = [int]$first.train_dates_read
        oos_dates_read = 0
        returns_read = $false
        pnl_computed = $false
        network_access = $false
        grid_search = $false
        retune = $false
        oos_schedule_path = $(if ($oosSchedule) { [System.IO.Path]::GetFullPath($OosSchedulePath) } else { $null })
        oos_schedule_file_sha256 = $(
            if ($oosSchedule) { (Get-FileHash -LiteralPath $OosSchedulePath -Algorithm SHA256).Hash.ToLowerInvariant() }
            else { $null }
        )
        oos_schedule_plan_hash = $(if ($oosSchedule) { [string]$oosSchedule.plan_hash } else { $null })
        oos_schedule_approval_phrase = $(if ($oosSchedule) { [string]$oosSchedule.approval_phrase } else { $null })
        next_allowed_action = $(
            if ($oosSchedule) { "await_explicit_night_schedule_approval" }
            else { [string]$first.next_allowed_action }
        )
        next_allowed_command = $(
            if ($oosSchedule) { [string]$oosSchedule.approval_phrase }
            else { [string]$first.next_allowed_command }
        )
        runtime_sec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
    }
    Write-JsonAtomic -Path $ManifestPath -Value $manifest
    Update-RunGate `
        -Status READY_FOR_POSTPROCESS `
        -Final $true `
        -CandidateEvents $manifest.rows `
        -StopReason $manifest.stop_condition `
        -Verdict $manifest.verdict `
        -PlanHash $planHash `
        -ResultHash $manifest.deterministic_result_hash `
        -OosPlanHash $manifest.oos_schedule_plan_hash
    Write-Host "VERDICT=$($manifest.verdict)" -ForegroundColor Green
    Write-Host "result_hash=$($manifest.deterministic_result_hash)"
    Write-Host "manifest=$ManifestPath"
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 0
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    $failurePath = Join-Path $ArtifactRoot "$RunId.failure.json"
    Write-JsonAtomic -Path $failurePath -Value ([ordered]@{
        schema = "pit_train_feasibility_failure_v1"
        run_id = $RunId
        final = $false
        created_at = (Get-Date).ToString("o")
        error = $message
        plan_path = $PlanPath
        feasibility_path = $FeasibilityPath
        repeat_feasibility_path = $RepeatFeasibilityPath
        oos_schedule_path = $OosSchedulePath
    })
    try {
        Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "train_feasibility_failed" -Failure $message
    } catch {
        Write-Warning "Could not update STOPPED_INCOMPLETE gate: $($_.Exception.Message)"
    }
    Write-Host "FAILED: $message" -ForegroundColor Red
    Write-Host "failure_artifact=$failurePath"
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 1
}
