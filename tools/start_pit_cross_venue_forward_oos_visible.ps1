param(
    [string]$PlanPath = "",
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\forward-oos",
    [string]$RunId = "",
    [switch]$PlanOnly,
    [switch]$ConfirmedForwardOosCollect,
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
$collectorModule = Join-Path $repoRoot "trading_mvp\src\pit_cross_venue_forward_collector.py"

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
        $Object | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Write-Result {
    param($Payload)
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 14
        return
    }
    Write-Host "Forward-OOS Visible Collector" -ForegroundColor Cyan
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
    $PlanPath = [string]$gate.forward_oos_plan_path
}
if ([string]::IsNullOrWhiteSpace($PlanPath) -or -not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "Forward-OOS plan not found. Pass -PlanPath explicitly."
}
$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
if ([string]$plan.schema -ne "pit_linear_perp_cross_venue_forward_oos_plan_v1" -or
    [string]$plan.decision -ne "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY") {
    throw "Unsupported or unready forward-OOS plan."
}
$planHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()

if ($ResumeIncomplete) {
    if ([string]$gateStatus.status -ne "STOPPED_INCOMPLETE") {
        throw "-ResumeIncomplete requires gate status STOPPED_INCOMPLETE."
    }
    if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId = [string]$gate.run_id }
} elseif ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "pit_linear_perp_forward_oos_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ([string]::IsNullOrWhiteSpace($RunId)) { throw "RunId is required." }

$runDir = Join-Path $OutputRoot $RunId
$segmentsDir = Join-Path $runDir "segments"
$manifestPath = Join-Path $runDir "manifest.json"
$launchRecordPath = Join-Path $runGateDir "$RunId.launch.json"
$resumeSwitchText = if ($ResumeIncomplete) { " -ResumeIncomplete" } else { "" }
$command = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
    "-PlanPath `"$PlanPath`"",
    "-OutputRoot `"$OutputRoot`"",
    "-RunId `"$RunId`"",
    "-ConfirmedForwardOosCollect$resumeSwitchText"
) -join " "
$planResult = [ordered]@{
    mode = if ($ResumeIncomplete) { "forward_oos_visible_resume_plan" } else { "forward_oos_visible_collect_plan" }
    would_start = [bool]($ConfirmedForwardOosCollect -and -not $PlanOnly)
    research_only = $true
    run_id = $RunId
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_root = $OutputRoot
    run_dir = $runDir
    segments_dir = $segmentsDir
    manifest_path = $manifestPath
    target_valid_cycles = [int]$plan.collection_contract.target_valid_cycles
    min_valid_pairs_per_cycle = [int]$plan.collection_contract.min_valid_pairs_per_cycle
    min_active_span_sec = [int]$plan.collection_contract.min_active_span_sec
    max_active_duration_sec = [int]$plan.collection_contract.max_active_duration_sec
    resume_incomplete = [bool]$ResumeIncomplete
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    command = $command
}
if ($PlanOnly -or -not $ConfirmedForwardOosCollect) {
    Write-Result $planResult
    exit 0
}

if ([string]$gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Refusing to start a duplicate collector."
}
if (-not $ResumeIncomplete -and
    [string]$gate.next_goal_decision -ne "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION") {
    throw "Forward-OOS collect is not the active approved gate step: $($gate.next_goal_decision)"
}
if ($ResumeIncomplete) {
    if ([string]$gate.run_id -ne $RunId) { throw "Resume run_id mismatch: gate=$($gate.run_id), requested=$RunId" }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Resume manifest not found: $manifestPath" }
    $resumeManifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ([bool]$resumeManifest.final) { throw "Cannot resume final=true run: $RunId" }
    if ([string]$resumeManifest.plan_sha256 -ne $planHash) { throw "Resume plan hash mismatch." }
}

if (-not $VisibleChild) {
    $childArgs = @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-PlanPath", "`"$PlanPath`"",
        "-OutputRoot", "`"$OutputRoot`"",
        "-RunId", "`"$RunId`"",
        "-ConfirmedForwardOosCollect",
        "-VisibleChild"
    )
    if ($ResumeIncomplete) { $childArgs += "-ResumeIncomplete" }
    $terminal = Start-Process -FilePath "pwsh.exe" -ArgumentList $childArgs -WindowStyle Normal -PassThru
    $planResult.mode = "forward_oos_visible_terminal_launched"
    $planResult.visible_terminal_pid = $terminal.Id
    Write-Result $planResult
    exit 0
}

$host.UI.RawUI.WindowTitle = "trading_mvp forward OOS - $RunId"
$python = Resolve-Python
if (-not (Test-Path -LiteralPath $OutputRoot)) { New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null }
if (-not (Test-Path -LiteralPath $runGateDir)) { New-Item -ItemType Directory -Path $runGateDir -Force | Out-Null }

if (-not $ResumeIncomplete) {
    if (Test-Path -LiteralPath $launchRecordPath) {
        throw "Immutable launch record already exists: $launchRecordPath"
    }
    $launchRecord = [ordered]@{
        schema = "active_run_launch_record_v1"
        project = "trading_mvp"
        run_id = $RunId
        run_type = "pit_linear_perp_cross_venue_forward_oos_collect"
        created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        command = $command
        cwd = $repoRoot
        plan_path = $PlanPath
        plan_sha256 = $planHash
        output_root = $OutputRoot
        run_dir = $runDir
        segments_dir = $segmentsDir
        manifest_path = $manifestPath
        target_valid_cycles = [int]$plan.collection_contract.target_valid_cycles
        min_valid_pairs_per_cycle = [int]$plan.collection_contract.min_valid_pairs_per_cycle
        min_active_span_sec = [int]$plan.collection_contract.min_active_span_sec
        max_active_duration_sec = [int]$plan.collection_contract.max_active_duration_sec
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
    }
    Write-JsonAtomic $launchRecord $launchRecordPath
}

Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "status" "RUNNING"
Set-JsonProperty $gate "gate_status" "RUNNING"
Set-JsonProperty $gate "run_id" $RunId
Set-JsonProperty $gate "purpose" "Research-only MEXC/Gate linear-perp forward-OOS evidence collect with immutable attempt segments and valid-cycle quota."
Set-JsonProperty $gate "started_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "monitor_pid" $PID
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @($PID)
Set-JsonProperty $gate "output_root" $OutputRoot
Set-JsonProperty $gate "output_path" $segmentsDir
Set-JsonProperty $gate "output_kind" "directory"
Set-JsonProperty $gate "manifest_path" $manifestPath
Set-JsonProperty $gate "launch_record_path" $launchRecordPath
Set-JsonProperty $gate "forward_oos_plan_path" $PlanPath
Set-JsonProperty $gate "forward_oos_plan_sha256" $planHash
Set-JsonProperty $gate "requested_duration_sec" ([int]$plan.collection_contract.max_active_duration_sec)
Set-JsonProperty $gate "target_valid_cycles" ([int]$plan.collection_contract.target_valid_cycles)
Set-JsonProperty $gate "min_valid_pairs_per_cycle" ([int]$plan.collection_contract.min_valid_pairs_per_cycle)
Set-JsonProperty $gate "final" $false
Set-JsonProperty $gate "stop_reason" $null
Set-JsonProperty $gate "next_goal_decision" "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_RUNNING"
Set-JsonProperty $gate "next_step_after_ready" "Wait for the visible forward-OOS collector. While RUNNING, only status/ETA checks are allowed."
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
    output = [ordered]@{ path = $segmentsDir; kind = "directory" }
    collector_pid = $null
    monitor_pid = $PID
    process_ids = @($PID)
    launch_record_path = $launchRecordPath
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "[forward-oos] visible collector starting" -ForegroundColor Cyan
Write-Host "[forward-oos] run_id=$RunId"
Write-Host "[forward-oos] target_valid_cycles=$($plan.collection_contract.target_valid_cycles)"
Write-Host "[forward-oos] valid_pairs_per_cycle>=$($plan.collection_contract.min_valid_pairs_per_cycle)"
Write-Host "[forward-oos] active duration=$([int]$plan.collection_contract.min_active_span_sec / 3600)-$([int]$plan.collection_contract.max_active_duration_sec / 3600)h"
Write-Host "[forward-oos] segments=$segmentsDir"

$pythonArgs = @(
    $collectorModule,
    "--plan", $PlanPath,
    "--output-root", $OutputRoot,
    "--run-id", $RunId,
    "--confirmed-forward-oos-collect"
)
if ($ResumeIncomplete) { $pythonArgs += "--resume" }
$collector = Start-Process -FilePath $python -ArgumentList $pythonArgs -NoNewWindow -PassThru
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
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
$qualityComplete = [bool]($manifest -and $manifest.quality_complete)
$nextStatus = if ($manifestFinal) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
$nextDecision = if ($qualityComplete) {
    "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
} elseif ($manifestFinal) {
    "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_COMPLETED_INSUFFICIENT_EVIDENCE"
} else {
    "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_STOPPED_INCOMPLETE"
}
$nextStep = if ($qualityComplete) {
    "Run forward-OOS data-quality PlanOnly. Replay/grid/live/API-key/paper-forward remain blocked."
} elseif ($manifestFinal) {
    "Inspect and reject/rescope the insufficient forward dataset. Do not replay or silently extend it."
} else {
    "Resume visibly with the same RunId and -ResumeIncomplete; immutable completed segments will be preserved."
}
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "status" $nextStatus
Set-JsonProperty $gate "gate_status" $nextStatus
Set-JsonProperty $gate "final" $manifestFinal
Set-JsonProperty $gate "quality_complete" $qualityComplete
Set-JsonProperty $gate "monitor_pid" $null
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @()
Set-JsonProperty $gate "stale_monitor_pid" $PID
Set-JsonProperty $gate "next_goal_decision" $nextDecision
Set-JsonProperty $gate "next_step_after_ready" $nextStep
Set-JsonProperty $gate "stop_reason" $(if ($manifest) { [string]$manifest.stop_reason } else { "collector_exit_$exitCode" })
Set-JsonProperty $gate "attempt_cycle_count" $(if ($manifest) { [int]$manifest.attempt_cycle_count } else { 0 })
Set-JsonProperty $gate "completed_cycles" $(if ($manifest) { [int]$manifest.valid_cycle_count } else { 0 })
Set-JsonProperty $gate "failed_cycle_count" $(if ($manifest) { [int]$manifest.failed_cycle_count } else { 0 })
Set-JsonProperty $gate "rows" $(if ($manifest) { [int]$manifest.pair_rows } else { 0 })
Set-JsonProperty $gate "resume_command" $(if ($manifestFinal) { $null } else { $command })
Write-JsonAtomic $gate $gatePath
$pointer.status = $nextStatus
$pointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
$pointer.collector_pid = $null
$pointer.monitor_pid = $null
$pointer.process_ids = @()
Write-JsonAtomic $pointer $currentRunPath

Write-Host "[forward-oos] status=$nextStatus decision=$nextDecision exit=$exitCode" -ForegroundColor Cyan
if ($exitCode -ne 0 -and $exitCode -ne 130) {
    throw "Forward-OOS collector failed with exit code $exitCode"
}
