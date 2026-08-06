param(
    [string]$PlanPath = "",
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\short-probe",
    [string]$RunId = "",
    [switch]$PlanOnly,
    [switch]$ConfirmedShortProbeCollect,
    [switch]$ResumeIncomplete,
    [switch]$VisibleChild,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$runGateDir = Join-Path $repoRoot "docs\agent-log\run-gates"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$collectorModule = Join-Path $repoRoot "trading_mvp\src\pit_cross_venue_short_probe_collector.py"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param($Object, [string]$Path)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temp = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Write-Result {
    param($Payload)
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 16
        return
    }
    Write-Host "Short Execution Probe Visible Collector" -ForegroundColor Cyan
    Write-Host "Mode: $($Payload.mode)"
    Write-Host "Would start: $($Payload.would_start)"
    Write-Host "RunId: $($Payload.run_id)"
    Write-Host "Plan: $($Payload.plan_path)"
    Write-Host "Run directory: $($Payload.run_dir)"
    if ($Payload.visible_terminal_pid) {
        Write-Host "Visible terminal PID: $($Payload.visible_terminal_pid)" -ForegroundColor Green
    }
    if ($Payload.command) {
        Write-Host "Command:"
        Write-Host "  $($Payload.command)"
    }
}

$gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($PlanPath)) {
    $PlanPath = [string]$gate.short_probe_plan_path
}
if ([string]::IsNullOrWhiteSpace($PlanPath) -or -not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "Short probe plan not found. Pass -PlanPath explicitly."
}
$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
if ([string]$plan.schema -ne "pit_linear_perp_cross_venue_short_execution_probe_plan_v1" -or
    [string]$plan.decision -ne "PIT_LINEAR_PERP_SHORT_EXECUTION_PROBE_PLANONLY_READY" -or
    [bool]$plan.would_start -or
    [bool]$plan.strategy_accepted) {
    throw "Unsupported or unsafe short probe plan."
}
$planHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()

if ($ResumeIncomplete) {
    if ([string]$gateStatus.status -ne "STOPPED_INCOMPLETE") {
        throw "-ResumeIncomplete requires gate status STOPPED_INCOMPLETE."
    }
    if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId = [string]$gate.run_id }
} elseif ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "pit_linear_perp_short_probe_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ([string]::IsNullOrWhiteSpace($RunId)) { throw "RunId is required." }

$runDir = Join-Path $OutputRoot $RunId
$samplesDir = Join-Path $runDir "samples"
$manifestPath = Join-Path $runDir "manifest.json"
$launchRecordPath = Join-Path $runGateDir "$RunId.launch.json"
$resumeSwitchText = if ($ResumeIncomplete) { " -ResumeIncomplete" } else { "" }
$command = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
    "-PlanPath `"$PlanPath`"",
    "-OutputRoot `"$OutputRoot`"",
    "-RunId `"$RunId`"",
    "-ConfirmedShortProbeCollect$resumeSwitchText"
) -join " "
$planResult = [ordered]@{
    mode = if ($ResumeIncomplete) { "short_probe_visible_resume_plan" } else { "short_probe_visible_collect_plan" }
    would_start = [bool]($ConfirmedShortProbeCollect -and -not $PlanOnly)
    research_only = $true
    run_id = $RunId
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_root = $OutputRoot
    run_dir = $runDir
    samples_dir = $samplesDir
    manifest_path = $manifestPath
    candidates = @($plan.instrument_scope.candidate_bases)
    interval_sec = [int]$plan.collection_contract.interval_sec
    min_duration_sec = [int]$plan.collection_contract.min_duration_sec
    max_duration_sec = [int]$plan.collection_contract.max_duration_sec
    quality_checkpoint_attempts = [int]$plan.sequential_stop_contract.quality_checkpoint_min_attempts
    futility_checkpoint_attempts = [int]$plan.sequential_stop_contract.futility_checkpoint_min_attempts
    target_valid_samples = [int]$plan.sequential_stop_contract.success_min_valid_samples
    automatic_long_run = $false
    resume_incomplete = [bool]$ResumeIncomplete
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    paper_forward_allowed = $false
    command = $command
}
if ($PlanOnly -or -not $ConfirmedShortProbeCollect) {
    Write-Result $planResult
    exit 0
}

if ([string]$gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Refusing to start a duplicate collector."
}
if (-not $ResumeIncomplete -and
    [string]$gate.next_goal_decision -ne "PIT_LINEAR_PERP_SHORT_EXECUTION_PROBE_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION") {
    throw "Short probe is not the active approved gate step: $($gate.next_goal_decision)"
}
if ($ResumeIncomplete) {
    if ([string]$gate.run_id -ne $RunId) { throw "Resume run_id mismatch." }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Resume manifest not found." }
    $resumeManifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ([bool]$resumeManifest.final) { throw "Cannot resume final=true run." }
    if ([string]$resumeManifest.plan_sha256 -ne $planHash) { throw "Resume plan hash mismatch." }
}

if (-not $VisibleChild) {
    $childArgs = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-PlanPath", "`"$PlanPath`"",
        "-OutputRoot", "`"$OutputRoot`"",
        "-RunId", "`"$RunId`"",
        "-ConfirmedShortProbeCollect", "-VisibleChild"
    )
    if ($ResumeIncomplete) { $childArgs += "-ResumeIncomplete" }
    $terminal = Start-Process -FilePath "pwsh.exe" -ArgumentList $childArgs -WindowStyle Normal -PassThru
    $planResult.mode = "short_probe_visible_terminal_launched"
    $planResult.visible_terminal_pid = $terminal.Id
    Write-Result $planResult
    exit 0
}

$host.UI.RawUI.WindowTitle = "trading_mvp short probe - $RunId"
$python = Resolve-Python
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runGateDir -Force | Out-Null
if (-not $ResumeIncomplete) {
    if (Test-Path -LiteralPath $launchRecordPath) { throw "Immutable launch record already exists." }
    $launchRecord = [ordered]@{
        schema = "active_run_launch_record_v1"
        project = "trading_mvp"
        run_id = $RunId
        run_type = "pit_linear_perp_cross_venue_short_execution_probe"
        created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        command = $command
        cwd = $repoRoot
        plan_path = $PlanPath
        plan_sha256 = $planHash
        output_root = $OutputRoot
        run_dir = $runDir
        samples_dir = $samplesDir
        manifest_path = $manifestPath
        max_duration_sec = [int]$plan.collection_contract.max_duration_sec
        research_only = $true
        live_orders = $false
        api_keys = $false
    }
    Write-JsonAtomic $launchRecord $launchRecordPath
}

Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "status" "RUNNING"
Set-JsonProperty $gate "gate_status" "RUNNING"
Set-JsonProperty $gate "run_id" $RunId
Set-JsonProperty $gate "purpose" "Research-only 1-3h public short execution probe with sequential early-stop gates."
Set-JsonProperty $gate "started_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "monitor_pid" $PID
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @($PID)
Set-JsonProperty $gate "output_root" $OutputRoot
Set-JsonProperty $gate "output_path" $samplesDir
Set-JsonProperty $gate "output_kind" "directory"
Set-JsonProperty $gate "manifest_path" $manifestPath
Set-JsonProperty $gate "launch_record_path" $launchRecordPath
Set-JsonProperty $gate "short_probe_plan_path" $PlanPath
Set-JsonProperty $gate "short_probe_plan_sha256" $planHash
Set-JsonProperty $gate "requested_duration_sec" ([int]$plan.collection_contract.max_duration_sec)
Set-JsonProperty $gate "final" $false
Set-JsonProperty $gate "next_goal_decision" "PIT_LINEAR_PERP_SHORT_EXECUTION_PROBE_RUNNING"
Set-JsonProperty $gate "next_step_after_ready" "Wait for sequential short-probe completion. While RUNNING, only status checks are allowed."
Set-JsonProperty $gate "resume_command" $command
Set-JsonProperty $gate "replay_allowed" $false
Set-JsonProperty $gate "grid_allowed" $false
Set-JsonProperty $gate "paper_forward_allowed" $false
Set-JsonProperty $gate "live_orders" $false
Set-JsonProperty $gate "api_keys" $false
Set-JsonProperty $gate "leverage_or_margin" $false
Write-JsonAtomic $gate $gatePath

$pointer = [ordered]@{
    schema = "active_run_pointer_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    manifest_path = $manifestPath
    output = [ordered]@{ path = $samplesDir; kind = "directory" }
    collector_pid = $null
    monitor_pid = $PID
    process_ids = @($PID)
    launch_record_path = $launchRecordPath
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "[short-probe] visible collector starting" -ForegroundColor Cyan
Write-Host "[short-probe] run_id=$RunId candidates=$(@($plan.instrument_scope.candidate_bases) -join ',')"
Write-Host "[short-probe] quality checkpoint=15m; futility checkpoint=30m; max=3h"
Write-Host "[short-probe] samples=$samplesDir"
$pythonArgs = @(
    $collectorModule, "--plan", $PlanPath, "--output-root", $OutputRoot,
    "--run-id", $RunId, "--confirmed-short-probe-collect"
)
if ($ResumeIncomplete) { $pythonArgs += "--resume" }
$collector = Start-Process -FilePath $python -ArgumentList $pythonArgs -NoNewWindow -PassThru
Set-JsonProperty $gate "collector_pid" $collector.Id
Set-JsonProperty $gate "process_ids" @($PID, $collector.Id)
Write-JsonAtomic $gate $gatePath
$pointer.collector_pid = $collector.Id
$pointer.process_ids = @($PID, $collector.Id)
$pointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
Write-JsonAtomic $pointer $currentRunPath
$collector.WaitForExit()
$exitCode = $collector.ExitCode

$manifest = if (Test-Path -LiteralPath $manifestPath) { Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json } else { $null }
$manifestFinal = [bool]($manifest -and $manifest.final)
$ready = [bool]($manifest -and $manifest.short_probe_ready_for_offline_evaluation)
$nextStatus = if ($manifestFinal) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
$nextDecision = if ($ready) {
    "PIT_LINEAR_PERP_SHORT_PROBE_COMPLETED_READY_FOR_OFFLINE_EVALUATION"
} elseif ($manifestFinal -and [string]$manifest.status -eq "COMPLETED_SHORT_PROBE_FUTILITY") {
    "PIT_LINEAR_PERP_SHORT_PROBE_REJECTED_FUTILITY"
} elseif ($manifestFinal) {
    "PIT_LINEAR_PERP_SHORT_PROBE_INSUFFICIENT_EVIDENCE_REJECT_OR_RESCOPE"
} else {
    "PIT_LINEAR_PERP_SHORT_PROBE_STOPPED_INCOMPLETE"
}
$nextStep = if ($ready) {
    "Run offline short-probe evaluation PlanOnly. Do not start a long run automatically."
} elseif ($manifestFinal) {
    "Reject or rescope this branch offline. Do not extend the probe automatically."
} else {
    "Resume visibly with the same RunId and -ResumeIncomplete; immutable samples are preserved."
}
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "status" $nextStatus
Set-JsonProperty $gate "gate_status" $nextStatus
Set-JsonProperty $gate "final" $manifestFinal
Set-JsonProperty $gate "monitor_pid" $null
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @()
Set-JsonProperty $gate "stale_monitor_pid" $PID
Set-JsonProperty $gate "next_goal_decision" $nextDecision
Set-JsonProperty $gate "next_step_after_ready" $nextStep
Set-JsonProperty $gate "stop_reason" $(if ($manifest) { [string]$manifest.stop_reason } else { "collector_exit_$exitCode" })
Set-JsonProperty $gate "attempt_sample_count" $(if ($manifest) { [int]$manifest.attempt_sample_count } else { 0 })
Set-JsonProperty $gate "valid_sample_count" $(if ($manifest) { [int]$manifest.valid_sample_count } else { 0 })
Set-JsonProperty $gate "failed_sample_count" $(if ($manifest) { [int]$manifest.failed_sample_count } else { 0 })
Set-JsonProperty $gate "fixed_cost_positive_observations" $(if ($manifest) { [int]$manifest.fixed_cost_positive_observations } else { 0 })
Set-JsonProperty $gate "independent_episodes" $(if ($manifest) { [int]$manifest.independent_episodes } else { 0 })
Set-JsonProperty $gate "rows" $(if ($manifest) { [int]$manifest.pair_rows } else { 0 })
Set-JsonProperty $gate "resume_command" $(if ($manifestFinal) { $null } else { $command })
Set-JsonProperty $gate "long_run_allowed" $false
Write-JsonAtomic $gate $gatePath
$pointer.status = $nextStatus
$pointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
$pointer.collector_pid = $null
$pointer.monitor_pid = $null
$pointer.process_ids = @()
Write-JsonAtomic $pointer $currentRunPath

Write-Host "[short-probe] status=$nextStatus decision=$nextDecision exit=$exitCode" -ForegroundColor Cyan
if ($exitCode -ne 0 -and $exitCode -ne 130) {
    throw "Short probe collector failed with exit code $exitCode"
}
