[CmdletBinding()]
param(
    [string]$PlanPath = "",
    [string]$ExpectedPlanHash = "a73a54627477030bea0d4c57395c717cf74b1a243862ef9f8726356780e50566",
    [string]$OutputPath = "",
    [string]$RepeatOutputPath = "",
    [ValidateRange(1, 1800)]
    [int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 60)]
    [int]$HoldOpenSec = 15,
    [string]$RunId = "",
    [switch]$PlanOnly,
    [switch]$Resume,
    [switch]$Worker
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v2"
$EvaluationRoot = Join-Path $DataRoot "evaluations"
$ManifestRoot = Join-Path $DataRoot "manifests"
$GatePaths = @(
    (Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"),
    (Join-Path $ProjectRoot "docs\agent-log\current-run.json")
)
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"

if (-not $PlanPath) {
    $PlanPath = Join-Path $DataRoot "plans\fast_first_residual_dispersion_planonly_20260713.json"
}
if (-not $RunId) {
    $RunId = "fast_first_v2_residual_dispersion_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $EvaluationRoot "$RunId.json"
}
if (-not $RepeatOutputPath) {
    $RepeatOutputPath = Join-Path $EvaluationRoot "$RunId.repeat.json"
}
$ManifestPath = Join-Path $ManifestRoot "$RunId.manifest.json"
$LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\$RunId.launch.json"

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
    $temporary = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Assert-ExternalArtifactPath {
    param([Parameter(Mandatory)][string]$Path)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($DataRoot).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Evaluation artifacts must stay under $DataRoot, observed: $fullPath"
    }
}

function Get-NextDecision {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") { return "FAST_FIRST_V2_EVALUATION_RUNNING" }
    if ($Status -eq "STOPPED_INCOMPLETE") { return "FAST_FIRST_V2_EVALUATION_STOPPED_INCOMPLETE" }
    switch ($Verdict) {
        "ACCEPT_FOR_SHORT_EXECUTION_PROBE" { return "FAST_FIRST_V2_ACCEPT_FOR_SHORT_EXECUTION_PROBE" }
        "REJECT" { return "FAST_FIRST_V2_REJECTED" }
        default { return "FAST_FIRST_V2_INSUFFICIENT_DATA" }
    }
}

function Get-NextStep {
    param([string]$Status, [string]$Verdict)
    if ($Status -eq "RUNNING") {
        return "Wait for the visible sealed evaluation and deterministic repeat to finish."
    }
    if ($Status -eq "STOPPED_INCOMPLETE") {
        return "Inspect the visible error and failure artifact; do not use partial metrics or start a probe."
    }
    if ($Verdict -eq "ACCEPT_FOR_SHORT_EXECUTION_PROBE") {
        return "Prepare a separate short execution-probe PlanOnly request; no probe, paper or live action is auto-started."
    }
    return "Freeze a genuinely new Fast-First hypothesis in PlanOnly; do not retune this rejected branch."
}

function Update-RunGate {
    param(
        [Parameter(Mandatory)][ValidateSet("RUNNING", "READY_FOR_POSTPROCESS", "STOPPED_INCOMPLETE")][string]$Status,
        [bool]$Final = $false,
        [int]$Errors = 0,
        [int]$EventCount = 0,
        [string]$StopReason = "",
        [string]$Verdict = "",
        [string]$ResultHash = "",
        [string]$Failure = ""
    )
    $now = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffffffK")
    $nextDecision = Get-NextDecision -Status $Status -Verdict $Verdict
    $nextStep = Get-NextStep -Status $Status -Verdict $Verdict
    foreach ($gatePath in $GatePaths) {
        if (-not (Test-Path -LiteralPath $gatePath)) {
            throw "Run gate is missing: $gatePath"
        }
        $document = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
        $fields = [ordered]@{
            project = "trading_mvp"
            run_id = $RunId
            status = $Status
            gate_status = $Status
            final = $Final
            primary_output_complete = ($Final -and (Test-Path -LiteralPath $OutputPath))
            expected_outputs_complete = ($Final -and (Test-Path -LiteralPath $RepeatOutputPath) -and (Test-Path -LiteralPath $ManifestPath))
            expected_outputs = [ordered]@{
                evaluation = $OutputPath
                repeat = $RepeatOutputPath
                manifest = $ManifestPath
            }
            updated_at = $now
            completed_cycles = $(if ($Final) { 2 } else { 0 })
            total_cycles = 2
            remaining_cycles = $(if ($Final) { 0 } else { 2 })
            rows = $EventCount
            errors = $Errors
            monitor_pid = $(if ($Status -eq "RUNNING") { $PID } else { $null })
            collector_pid = $null
            process_ids = $(if ($Status -eq "RUNNING") { @($PID) } else { @() })
            launch_record_path = $LaunchRecordPath
            output = [ordered]@{ path = $OutputPath; type = "fast_first_v2_residual_dispersion_evaluation" }
            evaluation_path = $OutputPath
            deterministic_repeat_path = $RepeatOutputPath
            manifest_path = $ManifestPath
            plan_path = $PlanPath
            plan_hash = $ExpectedPlanHash
            evaluation_result_hash = $ResultHash
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
            next_goal_decision = $nextDecision
            next_goal_reason = "Frozen residual-dispersion hypothesis evaluated without grid search or OOS tuning."
            next_step_after_ready = $nextStep
        }
        foreach ($entry in $fields.GetEnumerator()) {
            Set-ObjectProperty -Object $document -Name $entry.Key -Value $entry.Value
        }
        Write-JsonAtomic -Path $gatePath -Value $document
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

function Write-Stage {
    param([int]$Stage, [int]$Total, [string]$Message, [datetime]$StartedAt)
    $elapsed = [int]((Get-Date) - $StartedAt).TotalSeconds
    $remaining = [Math]::Max(0, $MaxRuntimeSec - $elapsed)
    Write-Host "[$Stage/$Total] $Message | elapsed=${elapsed}s | max_remaining=${remaining}s" -ForegroundColor Cyan
}

Assert-ExternalArtifactPath -Path $OutputPath
Assert-ExternalArtifactPath -Path $RepeatOutputPath
Assert-ExternalArtifactPath -Path $ManifestPath
if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "Frozen plan not found: $PlanPath"
}
if (-not (Test-Path -LiteralPath $GateChecker)) {
    throw "Gate checker not found: $GateChecker"
}
if (-not (Test-Path -LiteralPath $RunMvp)) {
    throw "run_mvp.ps1 not found: $RunMvp"
}

if (-not $Worker) {
    $gate = & $GateChecker -Json | ConvertFrom-Json
    if ([string]$gate.status -eq "RUNNING") {
        throw "Visible evaluation blocked by active gate status=$($gate.status), run_id=$($gate.run_id)"
    }
    if (
        [string]$gate.status -eq "STOPPED_INCOMPLETE" -and
        (-not $Resume -or [string]$gate.run_id -ne $RunId)
    ) {
        throw "STOPPED_INCOMPLETE may only be resumed visibly with -Resume and the same RunId=$($gate.run_id)"
    }
    $launchPlan = [ordered]@{
        schema = "fast_first_v2_visible_evaluation_launch_v1"
        mode = $(if ($PlanOnly) { "PLAN_ONLY" } elseif ($Resume) { "VISIBLE_RESUME" } else { "VISIBLE_WORKER" })
        run_id = $RunId
        plan_path = [System.IO.Path]::GetFullPath($PlanPath)
        expected_plan_hash = $ExpectedPlanHash
        output_path = [System.IO.Path]::GetFullPath($OutputPath)
        repeat_output_path = [System.IO.Path]::GetFullPath($RepeatOutputPath)
        manifest_path = [System.IO.Path]::GetFullPath($ManifestPath)
        max_runtime_sec = $MaxRuntimeSec
        visible_terminal = $true
        deterministic_repeats = 2
        grid_search = $false
        execution_probe = $false
        paper_forward = $false
        live_orders = $false
        api_keys = $false
    }
    if ($PlanOnly) {
        $launchPlan | ConvertTo-Json -Depth 10
        exit 0
    }

    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $workerArguments = @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Worker",
        "-RunId", "`"$RunId`"",
        "-PlanPath", "`"$PlanPath`"",
        "-ExpectedPlanHash", "`"$ExpectedPlanHash`"",
        "-OutputPath", "`"$OutputPath`"",
        "-RepeatOutputPath", "`"$RepeatOutputPath`"",
        "-MaxRuntimeSec", "$MaxRuntimeSec",
        "-HoldOpenSec", "$HoldOpenSec"
    )
    $startedAt = Get-Date
    $process = Start-Process -FilePath $pwsh -ArgumentList $workerArguments -WindowStyle Normal -PassThru
    $launchPlan.worker_pid = $process.Id
    $launchPlan.started_at = $startedAt.ToString("o")
    $launchPlan.expected_finish_not_later_than = $startedAt.AddSeconds($MaxRuntimeSec).ToString("o")
    $launchPlan.status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$GateChecker`""
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchPlan
    Write-Host "Visible Fast-First v2 evaluation opened. PID=$($process.Id)" -ForegroundColor Green
    Write-Host "Hard deadline: $($launchPlan.expected_finish_not_later_than)"
    Write-Host "Status: $($launchPlan.status_command)"
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Visible evaluation worker exited with code $($process.ExitCode)"
    }
    $finalGate = & $GateChecker -Json | ConvertFrom-Json
    $finalGate | ConvertTo-Json -Depth 10
    exit 0
}

$startedAt = Get-Date
$deadline = $startedAt.AddSeconds($MaxRuntimeSec)
Write-Host "trading_mvp Fast-First v2: visible sealed no-grid evaluation" -ForegroundColor Yellow
Write-Host "run_id=$RunId"
Write-Host "plan_hash=$ExpectedPlanHash"
Write-Host "hard_deadline=$($deadline.ToString('o'))"
Write-Host "outputs=$OutputPath ; $RepeatOutputPath"

try {
    Update-RunGate -Status RUNNING -StopReason "evaluation_started"
    Write-Stage -Stage 1 -Total 4 -Message "Validating frozen plan, CostProfile and all sealed input hashes" -StartedAt $startedAt
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-v2-validate",
        "-RunId", $RunId,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanHash", $ExpectedPlanHash,
        "-MaxRuntimeSec", $MaxRuntimeSec
    )

    Write-Stage -Stage 2 -Total 4 -Message "Running deterministic no-grid evaluation" -StartedAt $startedAt
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-v2-evaluate",
        "-RunId", $RunId,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanHash", $ExpectedPlanHash,
        "-OutputPath", $OutputPath,
        "-MaxRuntimeSec", $MaxRuntimeSec
    )
    $first = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    Write-Host "first_verdict=$($first.verdict) events=$($first.metrics.oos.event_count) hash=$($first.deterministic_result_hash)"

    Write-Stage -Stage 3 -Total 4 -Message "Repeating the frozen evaluation for reproducibility" -StartedAt $startedAt
    Invoke-RunMvpChild -Arguments @(
        "-Action", "fast-edge-v2-evaluate",
        "-RunId", $RunId,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanHash", $ExpectedPlanHash,
        "-OutputPath", $RepeatOutputPath,
        "-MaxRuntimeSec", $MaxRuntimeSec
    )
    $repeat = Get-Content -Raw -LiteralPath $RepeatOutputPath | ConvertFrom-Json
    if ([string]$first.deterministic_result_hash -ne [string]$repeat.deterministic_result_hash) {
        throw "Deterministic repeat mismatch: first=$($first.deterministic_result_hash), repeat=$($repeat.deterministic_result_hash)"
    }
    if ([string]$first.plan_hash -ne $ExpectedPlanHash -or [string]$repeat.plan_hash -ne $ExpectedPlanHash) {
        throw "Evaluation report is not bound to the expected frozen plan hash"
    }

    Write-Stage -Stage 4 -Total 4 -Message "Writing final manifest and closing the gate" -StartedAt $startedAt
    $manifest = [ordered]@{
        schema = "fast_first_v2_residual_dispersion_manifest_v1"
        run_id = $RunId
        project = "trading_mvp"
        final = $true
        completed_cycles = 2
        cycles = 2
        rows = [int]$first.metrics.oos.event_count
        errors = 0
        stop_condition = "completed_two_deterministic_evaluations"
        created_at = (Get-Date).ToString("o")
        plan_path = [System.IO.Path]::GetFullPath($PlanPath)
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()
        evaluation_path = [System.IO.Path]::GetFullPath($OutputPath)
        output_path = [System.IO.Path]::GetFullPath($OutputPath)
        evaluation_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
        deterministic_repeat_path = [System.IO.Path]::GetFullPath($RepeatOutputPath)
        deterministic_repeat_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $RepeatOutputPath).Hash.ToLowerInvariant()
        deterministic_repeat_equal = $true
        deterministic_result_hash = [string]$first.deterministic_result_hash
        verdict = [string]$first.verdict
        rejection_reasons = @($first.rejection_reasons)
        event_count = [int]$first.metrics.oos.event_count
        grid_search = $false
        execution_probe_started = $false
        paper_forward_started = $false
        live_orders = $false
        api_keys = $false
        runtime_sec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
    }
    Write-JsonAtomic -Path $ManifestPath -Value $manifest
    Update-RunGate `
        -Status READY_FOR_POSTPROCESS `
        -Final $true `
        -EventCount $manifest.event_count `
        -StopReason "completed_two_deterministic_evaluations" `
        -Verdict $manifest.verdict `
        -ResultHash $manifest.deterministic_result_hash

    Write-Host "VERDICT=$($manifest.verdict)" -ForegroundColor Green
    Write-Host "events=$($manifest.event_count) deterministic_hash=$($manifest.deterministic_result_hash)"
    Write-Host "manifest=$ManifestPath"
    if ($HoldOpenSec -gt 0) {
        Write-Host "Window closes in $HoldOpenSec seconds."
        Start-Sleep -Seconds $HoldOpenSec
    }
    exit 0
} catch {
    $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
    $failurePath = Join-Path $ManifestRoot "$RunId.failure.json"
    Write-JsonAtomic -Path $failurePath -Value ([ordered]@{
        schema = "fast_first_v2_evaluation_failure_v1"
        run_id = $RunId
        final = $false
        created_at = (Get-Date).ToString("o")
        error = $message
        plan_path = $PlanPath
        output_path = $OutputPath
        repeat_output_path = $RepeatOutputPath
    })
    try {
        Update-RunGate -Status STOPPED_INCOMPLETE -Errors 1 -StopReason "evaluation_failed" -Failure $message
    } catch {
        Write-Warning "Could not update STOPPED_INCOMPLETE gate: $($_.Exception.Message)"
    }
    Write-Host "FAILED: $message" -ForegroundColor Red
    Write-Host "failure_artifact=$failurePath"
    if ($HoldOpenSec -gt 0) {
        Start-Sleep -Seconds $HoldOpenSec
    }
    exit 1
}
