[CmdletBinding()]
param(
    [string]$RunId = "",
    [string]$ArtifactRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\pit-full-evaluation",
    [string]$QualityLedgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl",
    [string]$HypothesisBankPath = "",
    [string]$Hypothesis = "pit_universe_membership_drift_reversion_v1",
    [Parameter(Mandatory = $true)][string]$TrainPlanPath,
    [Parameter(Mandatory = $true)][string]$FeasibilityPath,
    [string]$FullPlanPath = "",
    [string]$EvaluationPath = "",
    [string]$RepeatEvaluationPath = "",
    [string]$ExecutionProbePlanPath = "",
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
    $RunId = "pit_full_evaluation_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
if (-not $FullPlanPath) {
    $FullPlanPath = Join-Path $ArtifactRoot "$RunId.full-input-plan.json"
}
if (-not $EvaluationPath) {
    $EvaluationPath = Join-Path $ArtifactRoot "$RunId.evaluation.json"
}
if (-not $RepeatEvaluationPath) {
    $RepeatEvaluationPath = Join-Path $ArtifactRoot "$RunId.evaluation.repeat.json"
}
if (-not $ExecutionProbePlanPath) {
    $ExecutionProbePlanPath = Join-Path $ArtifactRoot "$RunId.execution-probe-plan.json"
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
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $temporary -Encoding utf8
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
        throw "Full-evaluation outputs must stay under $ArtifactRoot, observed: $fullPath"
    }
}

function Get-GateStatus {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Run gate is missing: $Path" }
    $document = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $status = if ($document.gate_status) { [string]$document.gate_status } else { [string]$document.status }
    return [pscustomobject]@{ status = $status; run_id = [string]$document.run_id }
}

function Get-NextDecision {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") { return "PIT_FULL_EVALUATION_RUNNING" }
    if ($Status -eq "STOPPED_INCOMPLETE") { return "PIT_FULL_EVALUATION_STOPPED_INCOMPLETE" }
    if ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE") {
        return "PIT_ACCEPT_FOR_SHORT_EXECUTION_PROBE_REQUIRES_EXPLICIT_APPROVAL"
    }
    return "PIT_HYPOTHESIS_CLOSED_NO_RETUNE"
}

function Get-NextStep {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") {
        return "Wait for the visible owned no-grid OOS evaluation; do not launch another run."
    }
    if ($Status -eq "STOPPED_INCOMPLETE") {
        return "Inspect the visible failure and preserve partial artifacts; do not accept a partial verdict."
    }
    if ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE") {
        return "Request explicit user approval for one bounded short execution-probe PlanOnly; do not start it automatically."
    }
    return "Close the frozen hypothesis without retuning it on this evidence."
}

function Get-NextReason {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") {
        return "Owned visible full OOS evaluation is running under a hash-bound 20+100 split."
    }
    if ($Status -eq "STOPPED_INCOMPLETE") {
        return "Full OOS evaluation did not complete two matching external deterministic runs."
    }
    if ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE") {
        return "Frozen OOS, walk-forward, stress, concentration and execution-capacity gates passed historically."
    }
    return "The frozen branch failed or lacked evidence under the preregistered historical gates."
}

function Update-RunGate {
    param(
        [Parameter(Mandatory)][ValidateSet("RUNNING", "READY_FOR_POSTPROCESS", "STOPPED_INCOMPLETE")][string]$Status,
        [bool]$Final = $false,
        [int]$Errors = 0,
        [int]$Events = 0,
        [string]$StopReason = "",
        [string]$Verdict = "",
        [string]$PlanHash = "",
        [string]$ResultHash = "",
        [string]$Failure = "",
        [string]$ProbePlanPath = "",
        [string]$ProbePlanHash = "",
        [string]$ProbeApprovalPhrase = ""
    )
    $now = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffffffK")
    foreach ($path in $GatePaths) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Run gate is missing: $path" }
        $document = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $fields = [ordered]@{
            project = "trading_mvp"
            run_id = $RunId
            status = $Status
            gate_status = $Status
            final = $Final
            primary_output_complete = ($Final -and (Test-Path -LiteralPath $EvaluationPath))
            expected_outputs_complete = (
                $Final -and
                (Test-Path -LiteralPath $FullPlanPath) -and
                (Test-Path -LiteralPath $EvaluationPath) -and
                (Test-Path -LiteralPath $RepeatEvaluationPath) -and
                (Test-Path -LiteralPath $ManifestPath) -and
                ($Verdict -ne "ACCEPT_FOR_SHORT_EXECUTION_PROBE" -or (Test-Path -LiteralPath $ExecutionProbePlanPath))
            )
            expected_outputs = [ordered]@{
                full_input_plan = $FullPlanPath
                evaluation = $EvaluationPath
                deterministic_repeat = $RepeatEvaluationPath
                execution_probe_plan = $(if ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE") { $ExecutionProbePlanPath } else { $null })
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
            rows = $Events
            errors = $Errors
            monitor_pid = $(if ($Status -eq "RUNNING") { $PID } else { $null })
            collector_pid = $null
            process_ids = $(if ($Status -eq "RUNNING") { @($PID) } else { @() })
            launch_record_path = $LaunchRecordPath
            output = [ordered]@{ path = $EvaluationPath; type = "pit_full_oos_evaluation" }
            output_path = $EvaluationPath
            plan_path = $FullPlanPath
            plan_hash = $PlanHash
            deterministic_repeat_path = $RepeatEvaluationPath
            manifest_path = $ManifestPath
            evaluation_result_hash = $ResultHash
            verdict = $Verdict
            stop_reason = $StopReason
            failure = $Failure
            replay_allowed = $false
            grid_allowed = $false
            backtest_allowed = $false
            evaluation_allowed = $false
            execution_probe_allowed = ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE")
            requires_explicit_user_approval_for_execution_probe = ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE")
            execution_probe_plan_path = $(if ($ProbePlanPath) { $ProbePlanPath } else { $null })
            execution_probe_plan_hash = $(if ($ProbePlanHash) { $ProbePlanHash } else { $null })
            execution_probe_approval_phrase = $(if ($ProbeApprovalPhrase) { $ProbeApprovalPhrase } else { $null })
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
    if ($LASTEXITCODE -ne 0) { throw "run_mvp.ps1 failed with exit code $LASTEXITCODE" }
}

function Get-ApprovedDeadline {
    if (-not $ApprovedNotLaterThan) { return [DateTimeOffset](Get-Date).AddSeconds($MaxRuntimeSec) }
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
    if ($remaining -lt 1) { throw "Visible full evaluation reached its hard deadline." }
    return $remaining
}

function Write-Stage {
    param([int]$Stage, [int]$Total, [string]$Message, [datetime]$StartedAt)
    $elapsed = [int]((Get-Date) - $StartedAt).TotalSeconds
    $remaining = [Math]::Max(0, $MaxRuntimeSec - $elapsed)
    Write-Host "[$Stage/$Total] $Message | elapsed=${elapsed}s | max_remaining=${remaining}s" -ForegroundColor Cyan
}

foreach ($path in @($FullPlanPath, $EvaluationPath, $RepeatEvaluationPath, $ExecutionProbePlanPath, $ManifestPath)) {
    Assert-ArtifactPath -Path $path
}
foreach ($required in @(
    $QualityLedgerPath,
    $HypothesisBankPath,
    $TrainPlanPath,
    $FeasibilityPath,
    $CanonicalGoalPath,
    $RunMvp
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required input is missing: $required" }
}
if ((Get-FileHash -LiteralPath $CanonicalGoalPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $CanonicalGoalSha256) {
    throw "Canonical goal SHA-256 mismatch."
}

$launchPlan = [ordered]@{
    schema = "pit_full_evaluation_visible_launch_v1"
    decision = $(if ($PlanOnly) { "PLAN_ONLY" } elseif ($Worker) { "WORKER" } else { "VISIBLE_LAUNCH" })
    stage = "full_evaluation"
    run_id = $RunId
    artifact_root = [System.IO.Path]::GetFullPath($ArtifactRoot)
    quality_ledger_path = [System.IO.Path]::GetFullPath($QualityLedgerPath)
    hypothesis_bank_path = [System.IO.Path]::GetFullPath($HypothesisBankPath)
    hypothesis_id = $Hypothesis
    canonical_goal_path = [System.IO.Path]::GetFullPath($CanonicalGoalPath)
    canonical_goal_sha256 = $CanonicalGoalSha256
    train_plan_path = [System.IO.Path]::GetFullPath($TrainPlanPath)
    feasibility_path = [System.IO.Path]::GetFullPath($FeasibilityPath)
    full_plan_path = [System.IO.Path]::GetFullPath($FullPlanPath)
    evaluation_path = [System.IO.Path]::GetFullPath($EvaluationPath)
    repeat_evaluation_path = [System.IO.Path]::GetFullPath($RepeatEvaluationPath)
    execution_probe_plan_path = [System.IO.Path]::GetFullPath($ExecutionProbePlanPath)
    manifest_path = [System.IO.Path]::GetFullPath($ManifestPath)
    max_runtime_sec = $MaxRuntimeSec
    visible_terminal = $true
    external_deterministic_repeats = 2
    network_access = $false
    grid_search = $false
    retune = $false
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
        [string]$ownership.full_plan_path -ne [System.IO.Path]::GetFullPath($FullPlanPath) -or
        [string]$ownership.evaluation_path -ne [System.IO.Path]::GetFullPath($EvaluationPath) -or
        [string]$ownership.repeat_evaluation_path -ne [System.IO.Path]::GetFullPath($RepeatEvaluationPath) -or
        [string]$ownership.execution_probe_plan_path -ne [System.IO.Path]::GetFullPath($ExecutionProbePlanPath)
    ) {
        throw "Visible worker ownership record mismatch."
    }
    if ([string]$ownership.worker_token_sha256 -ne (Get-TextSha256 -Value $WorkerToken)) {
        throw "Visible worker ownership token mismatch."
    }
} else {
    $gate = Get-GateStatus -Path $GatePath
    if ($gate.status -eq "RUNNING") {
        throw "Visible full evaluation blocked by active gate status=RUNNING, run_id=$($gate.run_id)"
    }
    if ($gate.status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before starting full evaluation."
    }
    foreach ($output in @($FullPlanPath, $EvaluationPath, $RepeatEvaluationPath, $ExecutionProbePlanPath, $ManifestPath)) {
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
        "-TrainPlanPath", "`"$TrainPlanPath`"",
        "-FeasibilityPath", "`"$FeasibilityPath`"",
        "-FullPlanPath", "`"$FullPlanPath`"",
        "-EvaluationPath", "`"$EvaluationPath`"",
        "-RepeatEvaluationPath", "`"$RepeatEvaluationPath`"",
        "-ExecutionProbePlanPath", "`"$ExecutionProbePlanPath`"",
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
    Write-Host "Visible PIT full evaluation opened. PID=$($process.Id)" -ForegroundColor Green
    Write-Host "Hard deadline: $($deadline.ToString('o'))"
    $waitMs = ([int][Math]::Ceiling(($deadline - [DateTimeOffset]::Now).TotalMilliseconds)) + (($HoldOpenSec + 30) * 1000)
    if ($waitMs -lt 1000 -or -not $process.WaitForExit($waitMs)) {
        try { $process.Kill($true) } catch { }
        try { $process.WaitForExit(5000) } catch { }
        try {
            Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "full_evaluation_timeout" -Failure "Visible full-evaluation worker exceeded its hard deadline."
        } catch {
            Write-Warning "Could not close the timed-out full-evaluation gate: $($_.Exception.Message)"
        }
        throw "Visible full-evaluation worker exceeded its hard deadline."
    }
    if ($process.ExitCode -ne 0) {
        $gateAlreadyClosed = $false
        try {
            $workerGate = Get-GateStatus -Path $GatePath
            $gateAlreadyClosed = ($workerGate.run_id -eq $RunId -and $workerGate.status -eq "STOPPED_INCOMPLETE")
        } catch { }
        if (-not $gateAlreadyClosed) {
            try {
                Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "worker_exit_nonzero" -Failure "Visible full-evaluation worker exited with code $($process.ExitCode)."
            } catch {
                Write-Warning "Could not close the nonzero full-evaluation gate: $($_.Exception.Message)"
            }
        }
        throw "Visible full-evaluation worker exited with code $($process.ExitCode)"
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
try { $host.UI.RawUI.WindowTitle = "trading_mvp PIT full OOS evaluation - $RunId" } catch { }
Write-Host "trading_mvp PIT: visible owned full OOS evaluation" -ForegroundColor Yellow
Write-Host "run_id=$RunId"
Write-Host "hard_deadline=$($deadline.ToString('o'))"
Write-Host "quality_ledger=$QualityLedgerPath"

try {
    Update-RunGate -Status RUNNING -StopReason "full_evaluation_started"

    Write-Stage -Stage 1 -Total 5 -Message "Building immutable 20+100 full-evaluation input plan" -StartedAt $startedAt
    $remaining = [Math]::Min(1200, (Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline))
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-pit-input-plan",
        "-RunId", $RunId,
        "-ActiveRunGatePath", $GatePath,
        "-QualityLedgerPath", $QualityLedgerPath,
        "-HypothesisBankPath", $HypothesisBankPath,
        "-Hypothesis", $Hypothesis,
        "-PitPlanStage", "full_evaluation",
        "-TrainPlanPath", $TrainPlanPath,
        "-FeasibilityPath", $FeasibilityPath,
        "-OutputPath", $FullPlanPath,
        "-MaxRuntimeSec", $remaining
    )
    $plan = Get-Content -LiteralPath $FullPlanPath -Raw | ConvertFrom-Json
    $planHash = [string]$plan.plan_hash
    if (-not $planHash -or [string]$plan.sealed_input.plan_stage -ne "full_evaluation") {
        throw "Generated input plan is not a sealed full_evaluation plan."
    }
    if (@($plan.sealed_input.split.train_dates).Count -ne 20 -or @($plan.sealed_input.split.oos_dates).Count -ne 100) {
        throw "Full input plan must contain exactly 20 train dates and 100 untouched OOS dates."
    }
    if ([string]$plan.sealed_input.upstream_train_feasibility.feasibility.verdict -ne "FEASIBLE_FOR_OOS") {
        throw "Full input plan is not bound to a passed train feasibility artifact."
    }
    if ($plan.forward_market_rows_read -ne $false -or $plan.oos_returns_read -ne $false -or $plan.pnl_computed -ne $false) {
        throw "Full input PlanOnly read market returns or PnL before evaluation."
    }

    Write-Stage -Stage 2 -Total 5 -Message "Running frozen no-grid OOS evaluation" -StartedAt $startedAt
    $remaining = Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-pit-evaluate",
        "-RunId", $RunId,
        "-ActiveRunGatePath", $GatePath,
        "-PlanPath", $FullPlanPath,
        "-ExpectedPlanHash", $planHash,
        "-FeasibilityPath", $FeasibilityPath,
        "-OutputPath", $EvaluationPath,
        "-MaxRuntimeSec", $remaining
    )
    $first = Get-Content -LiteralPath $EvaluationPath -Raw | ConvertFrom-Json

    Write-Stage -Stage 3 -Total 5 -Message "Repeating full OOS evaluation for external deterministic equality" -StartedAt $startedAt
    $remaining = Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline
    $firstBackupPath = "$EvaluationPath.first.$PID.tmp"
    Move-Item -LiteralPath $EvaluationPath -Destination $firstBackupPath
    try {
        Invoke-RunMvpChild -Arguments @(
            "-Action", "fast-edge-pit-evaluate",
            "-RunId", $RunId,
            "-ActiveRunGatePath", $GatePath,
            "-PlanPath", $FullPlanPath,
            "-ExpectedPlanHash", $planHash,
            "-FeasibilityPath", $FeasibilityPath,
            "-OutputPath", $EvaluationPath,
            "-MaxRuntimeSec", $remaining
        )
        $repeat = Get-Content -LiteralPath $EvaluationPath -Raw | ConvertFrom-Json
        Move-Item -LiteralPath $EvaluationPath -Destination $RepeatEvaluationPath
    } finally {
        if (Test-Path -LiteralPath $firstBackupPath) {
            Move-Item -LiteralPath $firstBackupPath -Destination $EvaluationPath -Force
        }
    }
    if ([string]$first.deterministic_result_hash -ne [string]$repeat.deterministic_result_hash) {
        throw "External deterministic OOS evaluation repeat mismatch."
    }
    if ([string]$first.verdict -ne [string]$repeat.verdict) {
        throw "External deterministic OOS evaluation verdict mismatch."
    }
    if ([string]$first.verdict -notin @("ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA")) {
        throw "Unexpected full OOS verdict: $($first.verdict)"
    }
    foreach ($artifact in @($first, $repeat)) {
        if ([string]$artifact.plan_hash -ne $planHash) {
            throw "OOS evaluation artifact is not bound to the full input plan."
        }
        if (
            $artifact.deterministic_repeats_match -ne $true -or
            [int]$artifact.deterministic_repeats -ne 2 -or
            $artifact.network_access -ne $false -or
            $artifact.grid_search -ne $false -or
            $artifact.retune -ne $false -or
            $artifact.oos_tuning -ne $false -or
            $artifact.parameter_refit -ne $false -or
            $artifact.paper_forward_allowed -ne $false -or
            $artifact.live_orders -ne $false
        ) {
            throw "OOS evaluation artifact violated deterministic or research-only guards."
        }
        if ([int]$artifact.metrics.oos_closed_days -ne 100) {
            throw "OOS evaluation did not cover the frozen 100-day window."
        }
    }

    $executionProbePlan = $null
    Write-Stage -Stage 4 -Total 5 -Message "Preparing immutable execution-probe approval packet when historical gates pass" -StartedAt $startedAt
    if ([string]$first.verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE") {
        $remaining = Get-RemainingRuntimeSec -StartedAt $startedAt -Deadline $deadline
        Invoke-RunMvpChild -Arguments @(
            "-Action", "fast-edge-pit-execution-probe-plan",
            "-RunId", $RunId,
            "-ActiveRunGatePath", $GatePath,
            "-EvaluationPath", $EvaluationPath,
            "-OutputPath", $ExecutionProbePlanPath,
            "-MaxRuntimeSec", $remaining
        )
        $executionProbePlan = Get-Content -LiteralPath $ExecutionProbePlanPath -Raw | ConvertFrom-Json
        if (
            [string]$executionProbePlan.schema -ne "pit_membership_drift_execution_probe_plan_v1" -or
            [string]$executionProbePlan.source.evaluation_result_hash -ne [string]$first.deterministic_result_hash -or
            [int]$executionProbePlan.collection_contract.duration_sec -ne 1200 -or
            [double]$executionProbePlan.collection_contract.target_notional_quote_per_leg -ne 500.0 -or
            $executionProbePlan.would_start -ne $false -or
            $executionProbePlan.network_access -ne $false -or
            $executionProbePlan.paper_forward_allowed -ne $false -or
            $executionProbePlan.live_orders -ne $false
        ) {
            throw "Execution-probe approval packet violated the accepted OOS binding or safety contract."
        }
    }

    Write-Stage -Stage 5 -Total 5 -Message "Writing final manifest and closing gate" -StartedAt $startedAt
    $manifest = [ordered]@{
        schema = "pit_full_evaluation_manifest_v1"
        run_id = $RunId
        project = "trading_mvp"
        final = $true
        created_at = (Get-Date).ToString("o")
        stop_condition = "completed_two_external_deterministic_full_oos_evaluations"
        completed_cycles = 2
        cycles = 2
        rows = [int]$first.metrics.event_count
        errors = 0
        hypothesis_id = $Hypothesis
        canonical_goal_sha256 = $CanonicalGoalSha256
        train_plan_path = [System.IO.Path]::GetFullPath($TrainPlanPath)
        feasibility_path = [System.IO.Path]::GetFullPath($FeasibilityPath)
        full_plan_path = [System.IO.Path]::GetFullPath($FullPlanPath)
        full_plan_hash = $planHash
        full_plan_file_sha256 = (Get-FileHash -LiteralPath $FullPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
        evaluation_path = [System.IO.Path]::GetFullPath($EvaluationPath)
        evaluation_file_sha256 = (Get-FileHash -LiteralPath $EvaluationPath -Algorithm SHA256).Hash.ToLowerInvariant()
        repeat_evaluation_path = [System.IO.Path]::GetFullPath($RepeatEvaluationPath)
        repeat_evaluation_file_sha256 = (Get-FileHash -LiteralPath $RepeatEvaluationPath -Algorithm SHA256).Hash.ToLowerInvariant()
        external_deterministic_repeats = 2
        external_deterministic_repeats_match = $true
        deterministic_result_hash = [string]$first.deterministic_result_hash
        verdict = [string]$first.verdict
        rejection_reasons = @($first.rejection_reasons)
        metrics = $first.metrics
        walk_forward_folds = @($first.walk_forward_folds)
        execution_probe_plan_path = $(if ($executionProbePlan) { [System.IO.Path]::GetFullPath($ExecutionProbePlanPath) } else { $null })
        execution_probe_plan_file_sha256 = $(if ($executionProbePlan) { (Get-FileHash -LiteralPath $ExecutionProbePlanPath -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null })
        execution_probe_plan_hash = $(if ($executionProbePlan) { [string]$executionProbePlan.plan_hash } else { $null })
        execution_probe_approval_phrase = $(if ($executionProbePlan) { [string]$executionProbePlan.approval_phrase } else { $null })
        network_access = $false
        grid_search = $false
        retune = $false
        paper_forward_allowed = $false
        live_orders = $false
        next_allowed_action = [string]$first.next_allowed_action
        next_allowed_command = [string]$first.next_allowed_command
        runtime_sec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
    }
    Write-JsonAtomic -Path $ManifestPath -Value $manifest
    Update-RunGate `
        -Status READY_FOR_POSTPROCESS `
        -Final $true `
        -Events $manifest.rows `
        -StopReason $manifest.stop_condition `
        -Verdict $manifest.verdict `
        -PlanHash $planHash `
        -ResultHash $manifest.deterministic_result_hash `
        -ProbePlanPath $(if ($executionProbePlan) { $manifest.execution_probe_plan_path } else { "" }) `
        -ProbePlanHash $(if ($executionProbePlan) { $manifest.execution_probe_plan_hash } else { "" }) `
        -ProbeApprovalPhrase $(if ($executionProbePlan) { $manifest.execution_probe_approval_phrase } else { "" })
    Write-Host "VERDICT=$($manifest.verdict)" -ForegroundColor Green
    Write-Host "result_hash=$($manifest.deterministic_result_hash)"
    Write-Host "manifest=$ManifestPath"
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 0
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    $failurePath = Join-Path $ArtifactRoot "$RunId.failure.json"
    Write-JsonAtomic -Path $failurePath -Value ([ordered]@{
        schema = "pit_full_evaluation_failure_v1"
        run_id = $RunId
        final = $false
        created_at = (Get-Date).ToString("o")
        error = $message
        train_plan_path = $TrainPlanPath
        feasibility_path = $FeasibilityPath
        full_plan_path = $FullPlanPath
        evaluation_path = $EvaluationPath
        repeat_evaluation_path = $RepeatEvaluationPath
    })
    try {
        Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "full_evaluation_failed" -Failure $message
    } catch {
        Write-Warning "Could not update STOPPED_INCOMPLETE gate: $($_.Exception.Message)"
    }
    Write-Host "FAILED: $message" -ForegroundColor Red
    Write-Host "failure_artifact=$failurePath"
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 1
}
