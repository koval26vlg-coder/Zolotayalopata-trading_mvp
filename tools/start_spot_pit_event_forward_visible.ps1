param(
    [string]$ApprovalPacketPath = "",
    [string]$RunId = "",
    [switch]$PlanOnly,
    [switch]$ConfirmedSpotPitEventForwardCollect,
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
$expectedDecision = "SPOT_PIT_EVENT_FORWARD_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
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

function Assert-Artifact {
    param($Artifact, [string]$Name)
    $path = [string]$Artifact.path
    if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Sealed artifact is missing: $Name path=$path"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    $expected = ([string]$Artifact.sha256).ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "Sealed artifact hash mismatch: $Name expected=$expected actual=$actual"
    }
}

function Write-Result {
    param($Payload)
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 30
        return
    }
    Write-Host "Spot PIT Event Forward Collector" -ForegroundColor Cyan
    Write-Host "Mode: $($Payload.mode)"
    Write-Host "Would start: $($Payload.would_start)"
    Write-Host "RunId: $($Payload.run_id)"
    Write-Host "Run directory: $($Payload.run_dir)"
    Write-Host "Duration: $([math]::Round([double]$Payload.duration_sec / 86400, 2)) days; 48h futility gate enabled"
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
if ([string]$gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ([string]::IsNullOrWhiteSpace($ApprovalPacketPath)) {
    $ApprovalPacketPath = [string]$gate.spot_pit_event_forward_approval_packet_path
}
if ([string]::IsNullOrWhiteSpace($ApprovalPacketPath) -or -not (Test-Path -LiteralPath $ApprovalPacketPath -PathType Leaf)) {
    throw "Spot PIT event approval packet not found. Pass -ApprovalPacketPath."
}
$packet = Get-Content -Raw -LiteralPath $ApprovalPacketPath | ConvertFrom-Json
if ([string]$packet.schema -ne "spot_pit_event_forward_collect_approval_packet_v1" -or
    [string]$packet.decision -ne $expectedDecision -or
    -not [bool]$packet.all_checks_passed -or
    -not [bool]$packet.requires_explicit_user_confirmation) {
    throw "Approval packet is not ready for an explicitly confirmed research collect."
}
foreach ($name in @("plan", "preflight", "collector", "analyzer", "wrapper", "test_evidence")) {
    Assert-Artifact -Artifact $packet.artifacts.$name -Name $name
}

$planPath = [string]$packet.artifacts.plan.path
$preflightPath = [string]$packet.artifacts.preflight.path
$collectorPath = [string]$packet.artifacts.collector.path
$planHash = [string]$packet.artifacts.plan.sha256
$preflightHash = [string]$packet.artifacts.preflight.sha256
$outputRoot = [string]$packet.collection.output_root
$durationSec = [int]$packet.collection.duration_sec
$intervalSec = [int]$packet.collection.interval_sec
$segmentSec = [int]$packet.collection.segment_sec
$checkpointEvery = [int]$packet.collection.checkpoint_every_cycles

if ($ResumeIncomplete) {
    if ([string]$gateStatus.status -ne "STOPPED_INCOMPLETE") {
        throw "-ResumeIncomplete requires gate status STOPPED_INCOMPLETE."
    }
    if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId = [string]$gate.run_id }
} elseif ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "spot_pit_event_forward_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ([string]::IsNullOrWhiteSpace($RunId)) { throw "RunId is required." }

$runDir = Join-Path $outputRoot $RunId
$manifestPath = Join-Path $runDir "manifest.json"
$analysisPath = Join-Path $runDir "analysis.json"
$launchRecordPath = Join-Path $runGateDir "$RunId.launch.json"
$resumeText = if ($ResumeIncomplete) { " -ResumeIncomplete" } else { "" }
$command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ApprovalPacketPath `"$ApprovalPacketPath`" -RunId `"$RunId`" -ConfirmedSpotPitEventForwardCollect$resumeText"
$result = [ordered]@{
    mode = if ($ResumeIncomplete) { "spot_pit_event_forward_visible_resume_plan" } else { "spot_pit_event_forward_visible_collect_plan" }
    would_start = [bool]($ConfirmedSpotPitEventForwardCollect -and -not $PlanOnly)
    research_only = $true
    run_id = $RunId
    approval_packet_path = $ApprovalPacketPath
    output_root = $outputRoot
    run_dir = $runDir
    manifest_path = $manifestPath
    analysis_path = $analysisPath
    duration_sec = $durationSec
    interval_sec = $intervalSec
    segment_sec = $segmentSec
    resume_incomplete = [bool]$ResumeIncomplete
    visible_terminal_required = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    command = $command
}
if ($PlanOnly -or -not $ConfirmedSpotPitEventForwardCollect) {
    Write-Result $result
    exit 0
}

if (-not $ResumeIncomplete -and [string]$gate.next_goal_decision -ne $expectedDecision) {
    throw "Spot PIT event collect is not the active approved gate step: $($gate.next_goal_decision)"
}
if ($ResumeIncomplete) {
    if ([string]$gate.run_id -ne $RunId) { throw "Resume run_id mismatch: gate=$($gate.run_id), requested=$RunId" }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Resume manifest not found: $manifestPath" }
    $resumeManifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ([bool]$resumeManifest.final) { throw "Cannot resume final=true run: $RunId" }
    if ([string]$resumeManifest.plan_sha256 -ne $planHash -or [string]$resumeManifest.preflight_sha256 -ne $preflightHash) {
        throw "Resume artifact hash mismatch."
    }
} else {
    $preflight = Get-Content -Raw -LiteralPath $preflightPath | ConvertFrom-Json
    $preflightAgeHours = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse([string]$preflight.generated_at)).TotalHours
    if ($preflightAgeHours -gt [double]$packet.collection.preflight_max_age_hours_for_new_run) {
        throw "Public preflight is stale ($([math]::Round($preflightAgeHours, 2))h). Run a new short public preflight and rebuild the approval packet."
    }
}
$driveRoot = [System.IO.Path]::GetPathRoot($outputRoot)
$freeGiB = ([System.IO.DriveInfo]::new($driveRoot)).AvailableFreeSpace / 1GB
if ($freeGiB -lt [double]$packet.collection.minimum_free_disk_gib) {
    throw "Insufficient free disk on $driveRoot`: $([math]::Round($freeGiB, 2)) GiB."
}

if (-not $VisibleChild) {
    $childArgs = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-ApprovalPacketPath", "`"$ApprovalPacketPath`"",
        "-RunId", "`"$RunId`"",
        "-ConfirmedSpotPitEventForwardCollect", "-VisibleChild"
    )
    if ($ResumeIncomplete) { $childArgs += "-ResumeIncomplete" }
    $terminal = Start-Process -FilePath "pwsh.exe" -ArgumentList $childArgs -WindowStyle Normal -PassThru
    $result.mode = "spot_pit_event_forward_visible_terminal_launched"
    $result.visible_terminal_pid = $terminal.Id
    Write-Result $result
    exit 0
}

$host.UI.RawUI.WindowTitle = "trading_mvp spot PIT event forward - $RunId"
$python = Resolve-Python
if (-not (Test-Path -LiteralPath $outputRoot)) { New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null }
if (-not (Test-Path -LiteralPath $runGateDir)) { New-Item -ItemType Directory -Path $runGateDir -Force | Out-Null }
$launchMutex = [System.Threading.Mutex]::new($false, "Local\trading_mvp_spot_pit_event_forward_launch")
$launchMutexAcquired = $false
try {
    $launchMutexAcquired = $launchMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $launchMutexAcquired = $true
}
if (-not $launchMutexAcquired) {
    $launchMutex.Dispose()
    throw "Another spot PIT event launch is already in progress."
}
$freshGateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]$freshGateStatus.status -eq "RUNNING") {
    $launchMutex.ReleaseMutex()
    $launchMutex.Dispose()
    throw "A collector became RUNNING before launch. Refusing a duplicate."
}
if ($ResumeIncomplete) {
    if ([string]$freshGateStatus.status -ne "STOPPED_INCOMPLETE" -or [string]$gate.run_id -ne $RunId) {
        $launchMutex.ReleaseMutex()
        $launchMutex.Dispose()
        throw "Fresh resume gate no longer matches run_id=$RunId."
    }
} elseif ([string]$gate.next_goal_decision -ne $expectedDecision) {
    $launchMutex.ReleaseMutex()
    $launchMutex.Dispose()
    throw "Fresh gate no longer permits this new collect."
}
if (-not $ResumeIncomplete) {
    if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists: $runDir" }
    if (Test-Path -LiteralPath $launchRecordPath) { throw "Immutable launch record already exists: $launchRecordPath" }
    $launchRecord = [ordered]@{
        schema = "active_run_launch_record_v1"
        project = "trading_mvp"
        run_id = $RunId
        run_type = "spot_pit_event_forward_collect"
        created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        command = $command
        cwd = $repoRoot
        approval_packet_path = $ApprovalPacketPath
        approval_packet_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ApprovalPacketPath).Hash.ToLowerInvariant()
        plan_path = $planPath
        plan_sha256 = $planHash
        preflight_path = $preflightPath
        preflight_sha256 = $preflightHash
        output_root = $outputRoot
        run_dir = $runDir
        manifest_path = $manifestPath
        analysis_path = $analysisPath
        duration_sec = $durationSec
        interval_sec = $intervalSec
        segment_sec = $segmentSec
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
Set-JsonProperty $gate "purpose" "Visible research-only public MEXC/Gate spot PIT event forward collect with 2h quality and 48h futility gates."
Set-JsonProperty $gate "started_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gate "monitor_pid" $PID
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @($PID)
Set-JsonProperty $gate "output_root" $outputRoot
Set-JsonProperty $gate "output_path" $runDir
Set-JsonProperty $gate "output_kind" "directory"
Set-JsonProperty $gate "manifest_path" $manifestPath
Set-JsonProperty $gate "launch_record_path" $launchRecordPath
Set-JsonProperty $gate "requested_duration_sec" $durationSec
Set-JsonProperty $gate "final" $false
Set-JsonProperty $gate "stop_reason" $null
Set-JsonProperty $gate "next_goal_decision" "SPOT_PIT_EVENT_FORWARD_COLLECT_RUNNING"
Set-JsonProperty $gate "next_step_after_ready" "Wait for the visible collector. While RUNNING, only status/ETA checks are allowed."
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
    output = [ordered]@{ path = $runDir; kind = "directory" }
    collector_pid = $null
    monitor_pid = $PID
    process_ids = @($PID)
    launch_record_path = $launchRecordPath
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "[spot-pit] visible collector starting" -ForegroundColor Cyan
Write-Host "[spot-pit] run_id=$RunId"
Write-Host "[spot-pit] output=$runDir"
Write-Host "[spot-pit] duration=$([math]::Round($durationSec / 86400, 2))d; quality gate=2h; futility gate=48h"
Write-Host "[spot-pit] close this window only to interrupt; resume uses the same RunId" -ForegroundColor Yellow

$pythonArgs = @(
    $collectorPath,
    "--plan", $planPath,
    "--plan-sha256", $planHash,
    "--preflight", $preflightPath,
    "--preflight-sha256", $preflightHash,
    "--output-root", $outputRoot,
    "--run-id", $RunId,
    "--duration-sec", "$durationSec",
    "--interval-sec", "$intervalSec",
    "--segment-sec", "$segmentSec",
    "--analysis-output", $analysisPath,
    "--checkpoint-every-cycles", "$checkpointEvery"
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
$launchMutex.ReleaseMutex()
$launchMutex.Dispose()
$collector.WaitForExit()
$exitCode = $collector.ExitCode

$manifest = if (Test-Path -LiteralPath $manifestPath) { Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json } else { $null }
$analysis = if (Test-Path -LiteralPath $analysisPath) { Get-Content -Raw -LiteralPath $analysisPath | ConvertFrom-Json } else { $null }
$manifestFinal = [bool]($manifest -and $manifest.final)
$analysisDecision = if ($analysis) { [string]$analysis.decision } else { "" }
$nextStatus = if ($manifestFinal) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
if (-not $manifestFinal) {
    $nextDecision = "SPOT_PIT_EVENT_FORWARD_COLLECT_STOPPED_INCOMPLETE"
    $nextStep = "Inspect network/data-quality errors, then visibly resume the same RunId with -ResumeIncomplete."
} elseif ($analysisDecision -eq "SPOT_PIT_EVENT_FINAL_CANDIDATE_READY_FOR_INDEPENDENT_AUDIT_PLANONLY") {
    $nextDecision = "SPOT_PIT_EVENT_FORWARD_CANDIDATE_READY_FOR_INDEPENDENT_AUDIT_PLANONLY"
    $nextStep = "Run immutable artifact audit PlanOnly; replay/grid/live/API keys remain blocked."
} else {
    $nextDecision = "SPOT_PIT_EVENT_FORWARD_COMPLETED_REJECTED_BY_FIXED_GATES"
    $nextStep = "Close this fixed branch using the final analysis; do not tune it on the collected sample."
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
Set-JsonProperty $gate "completed_cycles" $(if ($manifest) { [int]$manifest.cycle_count } else { 0 })
Set-JsonProperty $gate "rows" $(if ($manifest) { [long]$manifest.rows_total } else { 0 })
Set-JsonProperty $gate "errors" $(if ($manifest) { [int]$manifest.errors_total } else { 1 })
Set-JsonProperty $gate "analysis_output_path" $(if ($analysis) { $analysisPath } else { $null })
Set-JsonProperty $gate "analysis_decision" $analysisDecision
Set-JsonProperty $gate "resume_command" $(if ($manifestFinal) { $null } else { $command })
Write-JsonAtomic $gate $gatePath
$pointer.status = $nextStatus
$pointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
$pointer.collector_pid = $null
$pointer.monitor_pid = $null
$pointer.process_ids = @()
Write-JsonAtomic $pointer $currentRunPath

Write-Host "[spot-pit] status=$nextStatus decision=$nextDecision exit=$exitCode" -ForegroundColor Cyan
if ($exitCode -ne 0 -and $exitCode -ne 3 -and $exitCode -ne 130) {
    throw "Spot PIT event collector failed with exit code $exitCode"
}
