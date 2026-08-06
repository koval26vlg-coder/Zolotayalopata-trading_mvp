[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-membership-drift-execution-probe",
    [string]$RunId = "",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [ValidateRange(1200, 1200)][int]$MaxRuntimeSec = 1200,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$PlanOnly,
    [switch]$ConfirmedExecutionProbe,
    [switch]$ResumeIncomplete,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
$ProbeCli = Join-Path $ProjectRoot "trading_mvp\src\pit_membership_drift_execution_probe.py"
$CollectorCli = Join-Path $ProjectRoot "trading_mvp\src\pit_membership_drift_execution_probe_collector.py"
$PaperCli = Join-Path $ProjectRoot "trading_mvp\src\pit_membership_drift_paper_forward.py"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $CurrentRunPath) { $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json" }
if (-not $RunId) { $RunId = "pit_membership_drift_execution_probe_$(Get-Date -Format 'yyyyMMdd_HHmmss')" }
$RunDirectory = Join-Path $OutputRoot $RunId
$ManifestPath = Join-Path $RunDirectory "manifest.json"
$SamplePath = Join-Path $RunDirectory "samples.jsonl"
$EvaluationPath = Join-Path $RunDirectory "execution-probe-evaluation.json"
$RepeatEvaluationPath = Join-Path $RunDirectory "execution-probe-evaluation.repeat.json"
$PaperPlanPath = Join-Path $RunDirectory "paper-forward-plan.json"
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\$RunId.launch.json"
}
$GatePaths = @($GatePath, $CurrentRunPath) | Select-Object -Unique

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    if ($candidates) { return [string]$candidates[0] }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable)"
        $resolvedPath = [string](@($resolved)[-1])
        if ($LASTEXITCODE -eq 0 -and $resolvedPath -and (Test-Path -LiteralPath $resolvedPath)) {
            return $resolvedPath
        }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return [string]$python.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Set-ObjectProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param([string]$Path, $Value)
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
    param([string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Get-Gate {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Active run gate not found: $Path" }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Set-RunGate {
    param(
        [ValidateSet("RUNNING", "READY_FOR_POSTPROCESS", "STOPPED_INCOMPLETE")][string]$Status,
        [string]$Decision,
        [string]$NextStep,
        [bool]$Final,
        [int]$Errors = 0,
        [string]$Verdict = "",
        [string]$ResultHash = "",
        [string]$PaperPlanHash = "",
        [string]$PaperApprovalPhrase = "",
        [string]$StopReason = ""
    )
    foreach ($path in $GatePaths) {
        $document = if (Test-Path -LiteralPath $path) { Get-Gate -Path $path } else { [pscustomobject]@{} }
        $fields = [ordered]@{
            schema = "active_run_gate_v2"
            project = "trading_mvp"
            run_id = $RunId
            status = $Status
            gate_status = $Status
            updated_at = (Get-Date).ToString("o")
            final = $Final
            errors = $Errors
            monitor_pid = $(if ($Status -eq "RUNNING") { $PID } else { $null })
            collector_pid = $null
            process_ids = $(if ($Status -eq "RUNNING") { @($PID) } else { @() })
            output = [ordered]@{ path = $SamplePath; kind = "file" }
            output_path = $SamplePath
            manifest_path = $ManifestPath
            evaluation_path = $EvaluationPath
            launch_record_path = $LaunchRecordPath
            execution_probe_plan_path = [System.IO.Path]::GetFullPath($PlanPath)
            execution_probe_plan_hash = $ExpectedPlanHash
            requested_duration_sec = $MaxRuntimeSec
            next_goal_decision = $Decision
            next_step_after_ready = $NextStep
            stop_reason = $StopReason
            verdict = $Verdict
            deterministic_result_hash = $ResultHash
            paper_forward_plan_path = $(if ($PaperPlanHash) { $PaperPlanPath } else { "" })
            paper_forward_plan_hash = $PaperPlanHash
            paper_forward_approval_phrase = $PaperApprovalPhrase
            paper_forward_started = $false
            replay_allowed = $false
            grid_allowed = $false
            backtest_allowed = $false
            paper_forward_allowed = ($Verdict -eq "PAPER_READY")
            requires_explicit_user_approval_for_paper_forward = ($Verdict -eq "PAPER_READY")
            live_orders = $false
            api_keys = $false
            leverage_or_margin = $false
        }
        foreach ($entry in $fields.GetEnumerator()) {
            Set-ObjectProperty -Object $document -Name $entry.Key -Value $entry.Value
        }
        Write-JsonAtomic -Path $path -Value $document
    }
}

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw "Execution-probe plan not found: $PlanPath" }
$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
if (
    [string]$plan.schema -ne "pit_membership_drift_execution_probe_plan_v1" -or
    [string]$plan.mode -ne "PlanOnly" -or
    [string]$plan.plan_hash -ne $ExpectedPlanHash -or
    [int]$plan.collection_contract.duration_sec -ne 1200 -or
    [int]$plan.collection_contract.interval_sec -ne 5 -or
    [double]$plan.collection_contract.target_notional_quote_per_leg -ne 500.0 -or
    [int]$plan.acceptance_gates.minimum_valid_snapshots -ne 180 -or
    [double]$plan.acceptance_gates.minimum_coverage_ratio -ne 0.80 -or
    [double]$plan.acceptance_gates.maximum_p95_impact_bps_per_leg -ne 10.0 -or
    $plan.would_start -ne $false -or
    $plan.network_access -ne $false -or
    $plan.live_orders -ne $false
) {
    throw "Execution-probe plan/hash/frozen gates are invalid."
}

$launchPlan = [ordered]@{
    schema = "pit_membership_drift_execution_probe_visible_launch_v1"
    decision = $(if ($PlanOnly) { "PLAN_ONLY" } elseif ($Worker) { "WORKER" } else { "VISIBLE_LAUNCH" })
    would_start = [bool]($ConfirmedExecutionProbe -and -not $PlanOnly)
    visible_terminal = $true
    run_id = $RunId
    plan_path = $PlanPath
    plan_file_sha256 = (Get-FileHash -LiteralPath $PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
    plan_hash = $ExpectedPlanHash
    approval_phrase = [string]$plan.approval_phrase
    output_root = [System.IO.Path]::GetFullPath($OutputRoot)
    run_directory = [System.IO.Path]::GetFullPath($RunDirectory)
    sample_path = [System.IO.Path]::GetFullPath($SamplePath)
    manifest_path = [System.IO.Path]::GetFullPath($ManifestPath)
    evaluation_path = [System.IO.Path]::GetFullPath($EvaluationPath)
    repeat_evaluation_path = [System.IO.Path]::GetFullPath($RepeatEvaluationPath)
    paper_forward_plan_path = [System.IO.Path]::GetFullPath($PaperPlanPath)
    duration_sec = 1200
    interval_sec = 5
    minimum_valid_snapshots = 180
    minimum_coverage_ratio = 0.80
    maximum_p95_impact_bps_per_leg = 10.0
    network_access = $false
    paper_forward = $false
    live_orders = $false
    api_keys = $false
    grid_search = $false
    retune = $false
    resume_incomplete = [bool]$ResumeIncomplete
}
if ($PlanOnly) {
    $launchPlan | ConvertTo-Json -Depth 20
    exit 0
}
if (-not $ConfirmedExecutionProbe) {
    throw "Actual public execution probe requires -ConfirmedExecutionProbe and exact -ExpectedPlanHash."
}

$python = Resolve-Python
$env:TRADING_MVP_PYTHON = $python
& $python $ProbeCli validate-plan --plan $PlanPath --expected-plan-hash $ExpectedPlanHash | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Full execution-probe plan validation failed." }

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Visible execution-probe worker requires an ownership token and launch record."
    }
    $ownership = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if (
        [string]$ownership.run_id -ne $RunId -or
        [string]$ownership.plan_hash -ne $ExpectedPlanHash -or
        [string]$ownership.worker_token_sha256 -ne (Get-TextSha256 -Value $WorkerToken)
    ) { throw "Visible execution-probe ownership mismatch." }
} else {
    $gate = Get-Gate -Path $GatePath
    $gateStatus = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
    if ($ResumeIncomplete) {
        if ($gateStatus -ne "STOPPED_INCOMPLETE" -or [string]$gate.run_id -ne $RunId) {
            throw "Resume requires STOPPED_INCOMPLETE for the same run_id."
        }
    } else {
        if ($gateStatus -eq "RUNNING" -or $gateStatus -eq "STOPPED_INCOMPLETE") {
            throw "Execution probe blocked by active gate status=$gateStatus."
        }
        if ([string]$gate.next_goal_decision -ne "PIT_ACCEPT_FOR_SHORT_EXECUTION_PROBE_REQUIRES_EXPLICIT_APPROVAL") {
            throw "Execution probe is not the next allowed gate step: $($gate.next_goal_decision)"
        }
        if (Test-Path -LiteralPath $RunDirectory) { throw "Refusing to overwrite execution-probe run: $RunDirectory" }
    }
    $token = [Guid]::NewGuid().ToString("N")
    $launchPlan.worker_token_sha256 = Get-TextSha256 -Value $token
    $launchPlan.launcher_pid = $PID
    $launchPlan.started_at = (Get-Date).ToString("o")
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $args = @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Worker", "-WorkerToken", "`"$token`"",
        "-ConfirmedExecutionProbe",
        "-PlanPath", "`"$PlanPath`"",
        "-ExpectedPlanHash", "`"$ExpectedPlanHash`"",
        "-OutputRoot", "`"$OutputRoot`"",
        "-RunId", "`"$RunId`"",
        "-GatePath", "`"$GatePath`"",
        "-CurrentRunPath", "`"$CurrentRunPath`"",
        "-LaunchRecordPath", "`"$LaunchRecordPath`"",
        "-MaxRuntimeSec", "$MaxRuntimeSec",
        "-HoldOpenSec", "$HoldOpenSec"
    )
    if ($ResumeIncomplete) { $args += "-ResumeIncomplete" }
    $process = Start-Process -FilePath $pwsh -ArgumentList $args -WindowStyle Normal -PassThru
    $launchPlan.worker_pid = $process.Id
    $launchPlan.status = "RUNNING"
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    Write-Host "Visible PIT execution probe opened. PID=$($process.Id) run_id=$RunId" -ForegroundColor Green
    exit 0
}

try { $host.UI.RawUI.WindowTitle = "trading_mvp PIT execution probe - $RunId" } catch { }
Write-Host "trading_mvp PIT membership-drift: visible 20m execution probe" -ForegroundColor Yellow
Write-Host "run_id=$RunId plan_hash=$ExpectedPlanHash"
Write-Host "gates: valid>=180 coverage>=80% p95_impact<=10bps notional=500/leg"
$workerGateOpened = $false
try {
Set-RunGate -Status RUNNING -Decision "PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_RUNNING" -NextStep "Wait for the visible bounded probe; only status checks are allowed." -Final $false -StopReason "execution_probe_started"
$workerGateOpened = $true

$collectorArgs = @(
    $CollectorCli,
    "--plan", $PlanPath,
    "--output-root", $OutputRoot,
    "--run-id", $RunId,
    "--confirmed-public-probe"
)
if ($ResumeIncomplete) { $collectorArgs += "--resume" }
$collector = Start-Process -FilePath $python -ArgumentList $collectorArgs -NoNewWindow -PassThru
foreach ($path in $GatePaths) {
    $document = Get-Gate -Path $path
    Set-ObjectProperty -Object $document -Name "collector_pid" -Value $collector.Id
    Set-ObjectProperty -Object $document -Name "process_ids" -Value @($PID, $collector.Id)
    Write-JsonAtomic -Path $path -Value $document
}

$hardDeadline = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec + 120)
$lastPrintedAttempt = -1
while (-not $collector.WaitForExit(5000)) {
    if (Test-Path -LiteralPath $ManifestPath) {
        $progress = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        $attempted = [int]$progress.attempted_snapshots
        if ($attempted -ne $lastPrintedAttempt) {
            $elapsed = [double]$progress.elapsed_active_sec
            $remaining = [Math]::Max(0, $MaxRuntimeSec - $elapsed)
            Write-Host ("[probe] elapsed={0:n0}s eta={1:n0}s attempted={2} valid={3} errors={4} last_write={5}" -f `
                $elapsed, $remaining, $attempted, [int]$progress.valid_snapshots, [int]$progress.fetch_errors, `
                (Get-Item -LiteralPath $ManifestPath).LastWriteTime.ToString("HH:mm:ss"))
            $lastPrintedAttempt = $attempted
        }
    }
    if ([DateTimeOffset]::Now -ge $hardDeadline) {
        try { $collector.Kill($true) } catch { }
        try { $collector.WaitForExit(5000) } catch { }
        throw "Execution-probe collector exceeded the 20m contract plus shutdown grace."
    }
}

$manifest = if (Test-Path -LiteralPath $ManifestPath) { Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json } else { $null }
if ($collector.ExitCode -ne 0 -or -not $manifest -or $manifest.final -ne $true) {
    Set-RunGate -Status STOPPED_INCOMPLETE -Decision "PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_STOPPED_INCOMPLETE" -NextStep "Resume visibly with the same run_id and exact plan hash; do not evaluate partial samples." -Final $false -Errors 1 -StopReason "collector_incomplete_or_failed"
    throw "Execution-probe collector stopped incomplete; resume the same run_id."
}

Write-Host "[probe] collection complete; running two offline deterministic evaluations" -ForegroundColor Cyan
& pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvp `
    -Action fast-edge-pit-execution-probe-evaluate -RunId $RunId -ActiveRunGatePath $GatePath `
    -PlanPath $PlanPath -ExpectedPlanHash $ExpectedPlanHash -ManifestPath $ManifestPath `
    -OutputPath $EvaluationPath -MaxRuntimeSec 300
if ($LASTEXITCODE -ne 0) { throw "First offline execution-probe evaluation failed." }
$first = Get-Content -LiteralPath $EvaluationPath -Raw | ConvertFrom-Json
$temporary = "$EvaluationPath.first.$PID.tmp"
Move-Item -LiteralPath $EvaluationPath -Destination $temporary
try {
    & pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvp `
        -Action fast-edge-pit-execution-probe-evaluate -RunId $RunId -ActiveRunGatePath $GatePath `
        -PlanPath $PlanPath -ExpectedPlanHash $ExpectedPlanHash -ManifestPath $ManifestPath `
        -OutputPath $EvaluationPath -MaxRuntimeSec 300
    if ($LASTEXITCODE -ne 0) { throw "Second offline execution-probe evaluation failed." }
    $second = Get-Content -LiteralPath $EvaluationPath -Raw | ConvertFrom-Json
    Move-Item -LiteralPath $EvaluationPath -Destination $RepeatEvaluationPath
} finally {
    if (Test-Path -LiteralPath $temporary) { Move-Item -LiteralPath $temporary -Destination $EvaluationPath -Force }
}
if (
    [string]$first.deterministic_result_hash -ne [string]$second.deterministic_result_hash -or
    [string]$first.verdict -ne [string]$second.verdict
) { throw "Execution-probe deterministic repeats diverged." }

$paperPlan = $null
if ([string]$first.verdict -eq "PAPER_READY") {
    Write-Host "[probe] PAPER_READY; creating immutable paper-forward PlanOnly only" -ForegroundColor Cyan
    & pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvp `
        -Action fast-edge-pit-paper-plan -RunId $RunId -ActiveRunGatePath $GatePath `
        -EvaluationPath $EvaluationPath -OutputPath $PaperPlanPath -MaxRuntimeSec 300
    if ($LASTEXITCODE -ne 0) { throw "Paper-forward PlanOnly creation failed." }
    $paperPlan = Get-Content -LiteralPath $PaperPlanPath -Raw | ConvertFrom-Json
    & $python $PaperCli validate-plan --plan $PaperPlanPath --expected-plan-hash ([string]$paperPlan.plan_hash) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Paper-forward PlanOnly validation failed." }
    if (
        [string]$paperPlan.decision -ne "PIT_PAPER_FORWARD_PLAN_READY_REQUIRES_EXPLICIT_APPROVAL" -or
        $paperPlan.paper_forward_started -ne $false -or
        $paperPlan.network_access -ne $false -or
        $paperPlan.live_orders -ne $false
    ) { throw "Paper-forward PlanOnly safety boundary is invalid." }
}

$decision = if ([string]$first.verdict -eq "PAPER_READY") {
    "PIT_PAPER_READY_REQUIRES_EXPLICIT_PAPER_FORWARD_APPROVAL"
} else { "PIT_EXECUTION_REJECTED_HYPOTHESIS_CLOSED_NO_RETUNE" }
$nextStep = if ([string]$first.verdict -eq "PAPER_READY") {
    "Request explicit approval for bounded paper-forward; do not start it automatically."
} else { "Close the frozen hypothesis without capacity reduction or retune." }
Set-RunGate -Status READY_FOR_POSTPROCESS -Decision $decision -NextStep $nextStep -Final $true `
    -Verdict ([string]$first.verdict) -ResultHash ([string]$first.deterministic_result_hash) `
    -PaperPlanHash $(if ($paperPlan) { [string]$paperPlan.plan_hash } else { "" }) `
    -PaperApprovalPhrase $(if ($paperPlan) { [string]$paperPlan.approval_phrase } else { "" }) `
    -StopReason "execution_probe_evaluated"
Write-Host "VERDICT=$($first.verdict)" -ForegroundColor Green
Write-Host "result_hash=$($first.deterministic_result_hash)"
Write-Host "evaluation=$EvaluationPath"
if ($paperPlan) {
    Write-Host "paper_plan=$PaperPlanPath"
    Write-Host "paper_plan_hash=$($paperPlan.plan_hash)"
    Write-Host "paper_approval_phrase=$($paperPlan.approval_phrase)" -ForegroundColor Yellow
    Write-Host "paper-forward was NOT approved or started" -ForegroundColor Yellow
}
if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    if ($workerGateOpened) {
        try {
            $currentGate = Get-Gate -Path $GatePath
            $currentStatus = if ($currentGate.gate_status) { [string]$currentGate.gate_status } else { [string]$currentGate.status }
            if ([string]$currentGate.run_id -eq $RunId -and $currentStatus -eq "RUNNING") {
                Set-RunGate -Status STOPPED_INCOMPLETE -Decision "PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_STOPPED_INCOMPLETE" -NextStep "Inspect the visible error and resume only the same run_id with the exact plan hash." -Final $false -Errors 1 -StopReason $message
            }
        } catch {
            Write-Warning "Could not close execution-probe gate: $($_.Exception.Message)"
        }
    }
    Write-Host "FAILED: $message" -ForegroundColor Red
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit 1
}
exit 0
