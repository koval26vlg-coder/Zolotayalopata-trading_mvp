param(
    [double]$Hours = 0.333333,
    [int]$DurationSec = 0,
    [int]$IntervalSec = 300,
    [int]$TimeoutSec = 10,
    [int]$MinContractsPerExchange = 50,
    [double]$MinFreeDiskGiB = 5.0,
    [string]$ApprovedNotBefore = "",
    [string]$ApprovedNotLaterThan = "",
    [string]$SchedulePlanPath = "",
    [string]$ExpectedSchedulePlanHash = "",
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2",
    [string]$RunId = "",
    [switch]$ConfirmedPitUniverseSnapshotCollect,
    [switch]$ResumeIncomplete,
    [switch]$PlanOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPointerPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$runGateDir = Join-Path $repoRoot "docs\agent-log\run-gates"
$modulePath = Join-Path $repoRoot "trading_mvp\src\pit_universe_snapshot_collector.py"
$nightScheduleValidatorPath = Join-Path $repoRoot "trading_mvp\src\night_schedule_plan.py"
$nightScheduleApprovalRoot = Join-Path $repoRoot "docs\agent-log\night-schedule-approvals"

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )

    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $jsonText = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $jsonText | ConvertFrom-Json -DateKind String
    }
    return $jsonText | ConvertFrom-Json
}

function ConvertTo-DateTimeOffsetInvariant {
    param([Parameter(Mandatory = $true)][string]$Value)

    return [DateTimeOffset]::Parse(
        $Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $tempPath = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

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
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Get-FreeDiskGiB {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Cannot resolve drive root for OutputRoot=$Path"
    }
    $drive = [System.IO.DriveInfo]::new($root)
    return [Math]::Round($drive.AvailableFreeSpace / 1GB, 3)
}

function Get-NightScheduleAuthorization {
    param(
        [Parameter(Mandatory = $true)]$GateDocument,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RequestedRunId,
        [Parameter(Mandatory = $true)][int]$RequestedDurationSec,
        [Parameter(Mandatory = $true)][int]$RequestedIntervalSec,
        [Parameter(Mandatory = $true)][string]$RequestedOutputRoot,
        [Parameter(Mandatory = $true)][string]$RequestedNotBefore,
        [Parameter(Mandatory = $true)][string]$RequestedNotLaterThan
    )

    if (-not $SchedulePlanPath -and -not $ExpectedSchedulePlanHash) {
        return $null
    }
    if (-not $SchedulePlanPath -or -not $ExpectedSchedulePlanHash) {
        throw "SchedulePlanPath and ExpectedSchedulePlanHash must be supplied together."
    }
    if (-not $GateDocument.approved_night_schedule) {
        throw "No approved_night_schedule is present in the active gate."
    }
    $approved = $GateDocument.approved_night_schedule
    $fullPlanPath = [System.IO.Path]::GetFullPath($SchedulePlanPath)
    if ([string]$approved.status -ne "ACTIVE") { throw "Approved night schedule is not ACTIVE." }
    if ([string]$approved.plan_hash -ne $ExpectedSchedulePlanHash) { throw "Approved night schedule hash mismatch." }
    if ([System.IO.Path]::GetFullPath([string]$approved.plan_path) -ne $fullPlanPath) { throw "Approved night schedule path mismatch." }
    if (-not (Test-Path -LiteralPath $fullPlanPath)) { throw "Night schedule plan is missing: $fullPlanPath" }

    $validationJson = & $Python $nightScheduleValidatorPath validate --plan $fullPlanPath --expected-plan-hash $ExpectedSchedulePlanHash
    if ($LASTEXITCODE -ne 0) { throw "Night schedule validation failed with exit code $LASTEXITCODE" }
    $validation = ConvertFrom-JsonPreserveDateStrings -InputJson $validationJson
    if ([string]$validation.plan_file_sha256 -ne [string]$approved.plan_file_sha256) {
        throw "Night schedule file SHA-256 no longer matches the approval."
    }

    $approvalRecordPath = [System.IO.Path]::GetFullPath([string]$approved.approval_record_path)
    if (-not (Test-Path -LiteralPath $approvalRecordPath)) { throw "Night schedule approval record is missing: $approvalRecordPath" }
    $approvalRecordSha256 = (Get-FileHash -LiteralPath $approvalRecordPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($approvalRecordSha256 -ne [string]$approved.approval_record_sha256) {
        throw "Night schedule approval record SHA-256 mismatch."
    }
    $approvalRecord = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $approvalRecordPath -Raw)
    if ([string]$approvalRecord.status -ne "ACTIVE" -or [string]$approvalRecord.plan_hash -ne $ExpectedSchedulePlanHash) {
        throw "Night schedule approval record is not active for this plan."
    }
    if ([DateTimeOffset]::Now -gt (ConvertTo-DateTimeOffsetInvariant -Value ([string]$approvalRecord.expires_at))) {
        throw "Night schedule approval has expired."
    }
    if (@($approvalRecord.segment_run_ids) -notcontains $RequestedRunId) {
        throw "RunId=$RequestedRunId is not authorized by the approved night schedule."
    }

    $plan = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullPlanPath -Raw)
    $segment = @($plan.segments | Where-Object { [string]$_.run_id -eq $RequestedRunId })
    if ($segment.Count -ne 1) { throw "Expected exactly one schedule segment for RunId=$RequestedRunId." }
    $segment = $segment[0]
    if ([int]$segment.duration_sec -ne $RequestedDurationSec) { throw "Schedule duration mismatch for RunId=$RequestedRunId." }
    if ([int]$segment.interval_sec -ne $RequestedIntervalSec) { throw "Schedule interval mismatch for RunId=$RequestedRunId." }
    if ([System.IO.Path]::GetFullPath([string]$plan.output_root) -ne [System.IO.Path]::GetFullPath($RequestedOutputRoot)) {
        throw "Schedule output root mismatch for RunId=$RequestedRunId."
    }
    if ([string]$segment.start_local -ne $RequestedNotBefore) { throw "Schedule not-before mismatch for RunId=$RequestedRunId." }
    if ([string]$segment.hard_deadline_local -ne $RequestedNotLaterThan) { throw "Schedule deadline mismatch for RunId=$RequestedRunId." }

    $stageAuthorizationJson = & $Python $nightScheduleValidatorPath authorize-segment `
        --plan $fullPlanPath `
        --expected-plan-hash $ExpectedSchedulePlanHash `
        --run-id $RequestedRunId
    if ($LASTEXITCODE -ne 0) {
        throw "Collection-stage authorization failed for RunId=$RequestedRunId with exit code $LASTEXITCODE"
    }
    $stageAuthorization = ConvertFrom-JsonPreserveDateStrings -InputJson $stageAuthorizationJson
    if ([string]$stageAuthorization.verdict -ne "AUTHORIZED") {
        throw "Collection-stage authorization did not return AUTHORIZED for RunId=$RequestedRunId"
    }
    if ([string]$approvalRecord.collection_stage -ne [string]$stageAuthorization.collection_stage) {
        throw "Approval collection stage mismatch for RunId=$RequestedRunId"
    }
    if ([System.IO.Path]::GetFullPath([string]$approvalRecord.quality_ledger_path) -ne [System.IO.Path]::GetFullPath([string]$stageAuthorization.quality_ledger_path)) {
        throw "Approval quality ledger path mismatch for RunId=$RequestedRunId"
    }

    return [ordered]@{
        plan_path = $fullPlanPath
        plan_hash = $ExpectedSchedulePlanHash
        plan_file_sha256 = [string]$validation.plan_file_sha256
        approval_record_path = $approvalRecordPath
        approval_record_sha256 = $approvalRecordSha256
        run_id = $RequestedRunId
        sequence = [int]$segment.sequence
        collection_stage = [string]$stageAuthorization.collection_stage
        quality_ledger_path = [string]$stageAuthorization.quality_ledger_path
        accepted_distinct_dates_before_run = [int]$stageAuthorization.accepted_distinct_dates_before_run
        remaining_stage_dates_before_run = [int]$stageAuthorization.remaining_stage_dates_before_run
    }
}

function Write-JsonOrText {
    param($Payload)

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }

    Write-Host "PIT Universe Snapshot Collect Visible" -ForegroundColor Cyan
    Write-Host "Mode: $($Payload.mode)"
    Write-Host "Would start: $($Payload.would_start)"
    Write-Host "RunId: $($Payload.run_id)"
    Write-Host "Output root: $($Payload.output_root)"
    Write-Host "Command:"
    Write-Host "  $($Payload.command)"
}

$gate = ConvertFrom-JsonPreserveDateStrings -InputJson (& pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json)
if ([string]$gate.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ([string]$gate.status -eq "STOPPED_INCOMPLETE" -and -not $ResumeIncomplete) {
    throw "Active run gate is STOPPED_INCOMPLETE. Resume/reject incomplete run before starting a new collect."
}

$gateDoc = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -Raw -LiteralPath $gatePath)

if ($DurationSec -le 0) {
    $DurationSec = [int][Math]::Round($Hours * 3600)
}
if ($DurationSec -lt 1 -or $DurationSec -gt 10800) {
    throw "DurationSec must be in [1, 10800] for Fast-First PIT segments."
}
if ($IntervalSec -lt 1 -or $IntervalSec -gt $DurationSec) {
    throw "IntervalSec must be in [1, DurationSec]."
}
if ($MinFreeDiskGiB -lt 0) {
    throw "MinFreeDiskGiB must be non-negative."
}

$now = [DateTimeOffset]::Now
$notBefore = if ($ApprovedNotBefore) { ConvertTo-DateTimeOffsetInvariant -Value $ApprovedNotBefore } else { $null }
$notLater = if ($ApprovedNotLaterThan) { ConvertTo-DateTimeOffsetInvariant -Value $ApprovedNotLaterThan } else { $null }
if ($ConfirmedPitUniverseSnapshotCollect -and -not $PlanOnly) {
    if ($notBefore -and $now -lt $notBefore) {
        throw "Approved PIT window has not opened: now=$($now.ToString('o')) not_before=$($notBefore.ToString('o'))"
    }
    if ($notLater -and $now.AddSeconds($DurationSec) -gt $notLater) {
        throw "PIT segment cannot finish before approved deadline: now=$($now.ToString('o')) duration_sec=$DurationSec not_later=$($notLater.ToString('o'))"
    }
    $freeDiskGiB = Get-FreeDiskGiB -Path $OutputRoot
    if ($freeDiskGiB -lt $MinFreeDiskGiB) {
        throw "disk_space_below_threshold: free_gib=$freeDiskGiB required_gib=$MinFreeDiskGiB output_root=$OutputRoot"
    }
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    if ($ResumeIncomplete) {
        throw "-ResumeIncomplete requires the existing -RunId."
    }
    $RunId = "pit_universe_snapshot_collect_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}

$python = Resolve-Python
$scheduleAuthorization = Get-NightScheduleAuthorization `
    -GateDocument $gateDoc `
    -Python $python `
    -RequestedRunId $RunId `
    -RequestedDurationSec $DurationSec `
    -RequestedIntervalSec $IntervalSec `
    -RequestedOutputRoot $OutputRoot `
    -RequestedNotBefore $ApprovedNotBefore `
    -RequestedNotLaterThan $ApprovedNotLaterThan
$allowed = (
    $ResumeIncomplete -or
    $null -ne $scheduleAuthorization -or
    [string]$gateDoc.next_goal_decision -eq "START_NEW_VISIBLE_PIT_UNIVERSE_SNAPSHOT_COLLECT_AFTER_FIX_APPROVAL" -or
    [string]$gateDoc.next_goal_decision -eq "PIT_UNIVERSE_FIXES_COMPLETE_READY_FOR_NEW_CLEAN_COLLECT_APPROVAL" -or
    [string]$gateDoc.next_goal_decision -eq "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL" -or
    [string]$gateDoc.next_goal_decision -eq "PIT_UNIVERSE_SNAPSHOT_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION" -or
    (
        $gateDoc.strategy_branch_status -and
        [string]$gateDoc.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gateDoc.strategy_branch_status.verdict -in @(
            "pit_public_probe_accepted_ready_for_visible_snapshot_collect_approval",
            "snapshot_collect_approval_packet_ready_awaiting_explicit_confirmation"
        )
    )
)
if (-not $allowed) {
    throw "PIT universe snapshot collect is not the active gate step. Current next_goal_decision=$($gateDoc.next_goal_decision)"
}
$runDir = Join-Path $OutputRoot $RunId
$snapshotPath = Join-Path $runDir "snapshots.jsonl"
$cyclesPath = Join-Path $runDir "cycles.jsonl"
$manifestPath = Join-Path $runDir "manifest.json"
$launchRecordPath = Join-Path $runGateDir "$RunId.launch.json"
if ($ResumeIncomplete) {
    if ([string]$gateDoc.run_id -ne $RunId) {
        throw "Resume run_id mismatch: gate=$($gateDoc.run_id), requested=$RunId"
    }
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "Resume manifest not found: $manifestPath"
    }
    $resumeManifest = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -Raw -LiteralPath $manifestPath)
    $expectedResumeSchema = "pit_universe_snapshot_manifest_v2"
    if ([string]$resumeManifest.schema -ne $expectedResumeSchema) {
        throw "Resume incompatible: expected manifest schema=$expectedResumeSchema, observed=$($resumeManifest.schema). Start a new clean RunId."
    }
    if ([bool]$resumeManifest.final) {
        throw "Cannot resume final=true run: $RunId"
    }
    if ([int]($resumeManifest.cycle_count) -gt 0 -and -not (Test-Path -LiteralPath $cyclesPath)) {
        throw "Resume incompatible: cycles.jsonl is missing for completed cycles. Start a new clean RunId."
    }
    if (-not (Test-Path -LiteralPath $launchRecordPath)) {
        throw "Resume incompatible: immutable launch record is missing: $launchRecordPath. Start a new clean RunId."
    }
}
$resumeArg = if ($ResumeIncomplete) { " -ResumeIncomplete" } else { "" }
$notBeforeArg = if ($ApprovedNotBefore) { " -ApprovedNotBefore `"$ApprovedNotBefore`"" } else { "" }
$notLaterArg = if ($ApprovedNotLaterThan) { " -ApprovedNotLaterThan `"$ApprovedNotLaterThan`"" } else { "" }
$scheduleArg = if ($SchedulePlanPath) { " -SchedulePlanPath `"$SchedulePlanPath`" -ExpectedSchedulePlanHash $ExpectedSchedulePlanHash" } else { "" }
$command = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
    "-Hours $Hours",
    "-DurationSec $DurationSec",
    "-IntervalSec $IntervalSec",
    "-TimeoutSec $TimeoutSec",
    "-MinContractsPerExchange $MinContractsPerExchange",
    "-MinFreeDiskGiB $MinFreeDiskGiB",
    "-OutputRoot `"$OutputRoot`"",
    "-RunId $RunId",
    "-ConfirmedPitUniverseSnapshotCollect$resumeArg$notBeforeArg$notLaterArg$scheduleArg"
) -join " "

$plan = [ordered]@{
    mode = "pit_universe_snapshot_collect_visible_plan"
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    would_start = [bool]($ConfirmedPitUniverseSnapshotCollect -and -not $PlanOnly)
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    run_id = $RunId
    output_root = $OutputRoot
    run_dir = $runDir
    snapshots_path = $snapshotPath
    cycles_path = $cyclesPath
    manifest_path = $manifestPath
    current_run_pointer_path = $currentRunPointerPath
    launch_record_path = $launchRecordPath
    duration_sec = $DurationSec
    interval_sec = $IntervalSec
    timeout_sec = $TimeoutSec
    min_contracts_per_exchange = $MinContractsPerExchange
    min_free_disk_gib = $MinFreeDiskGiB
    approved_not_before = $ApprovedNotBefore
    approved_not_later_than = $ApprovedNotLaterThan
    approved_night_schedule = $scheduleAuthorization
    resume_incomplete = [bool]$ResumeIncomplete
    command = $command
}

if ($PlanOnly -or -not $ConfirmedPitUniverseSnapshotCollect) {
    Write-JsonOrText -Payload $plan
    exit 0
}

if (-not (Test-Path -LiteralPath $OutputRoot)) {
    New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
}
if (-not (Test-Path -LiteralPath $runGateDir)) {
    New-Item -ItemType Directory -Force -Path $runGateDir | Out-Null
}
if (-not $ResumeIncomplete) {
    if (Test-Path -LiteralPath $launchRecordPath) {
        throw "Immutable launch record already exists for RunId=${RunId}: $launchRecordPath"
    }
    $launchRecord = [ordered]@{
        schema = "active_run_launch_record_v1"
        project = "trading_mvp"
        run_id = $RunId
        run_type = "pit_universe_snapshot_collect"
        created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        command = $command
        cwd = $repoRoot
        output_root = $OutputRoot
        snapshots_path = $snapshotPath
        cycles_path = $cyclesPath
        manifest_path = $manifestPath
        duration_sec = $DurationSec
        interval_sec = $IntervalSec
        timeout_sec = $TimeoutSec
        min_contracts_per_exchange = $MinContractsPerExchange
        min_free_disk_gib = $MinFreeDiskGiB
        approved_not_before = $ApprovedNotBefore
        approved_not_later_than = $ApprovedNotLaterThan
        approved_night_schedule = $scheduleAuthorization
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
    }
    Write-JsonAtomic -Object $launchRecord -Path $launchRecordPath
}

Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty -Object $gateDoc -Name "status" -Value "RUNNING"
Set-JsonProperty -Object $gateDoc -Name "gate_status" -Value "RUNNING"
Set-JsonProperty -Object $gateDoc -Name "schema" -Value "active_run_gate_v2"
Set-JsonProperty -Object $gateDoc -Name "project" -Value "trading_mvp"
Set-JsonProperty -Object $gateDoc -Name "run_id" -Value $RunId
Set-JsonProperty -Object $gateDoc -Name "started_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty -Object $gateDoc -Name "requested_duration_sec" -Value $DurationSec
Set-JsonProperty -Object $gateDoc -Name "output" -Value ([ordered]@{ path = $snapshotPath; kind = "file" })
Set-JsonProperty -Object $gateDoc -Name "output_path" -Value $snapshotPath
Set-JsonProperty -Object $gateDoc -Name "manifest_path" -Value $manifestPath
Set-JsonProperty -Object $gateDoc -Name "monitor_pid" -Value $PID
Set-JsonProperty -Object $gateDoc -Name "collector_pid" -Value $null
Set-JsonProperty -Object $gateDoc -Name "process_ids" -Value @($PID)
Set-JsonProperty -Object $gateDoc -Name "final" -Value $false
Set-JsonProperty -Object $gateDoc -Name "stop_reason" -Value $null
Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value "PIT_UNIVERSE_SNAPSHOT_COLLECT_RUNNING"
Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Wait for visible PIT universe snapshot collect to finish; only status/ETA checks are allowed while RUNNING."
Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value ([bool]($null -eq $scheduleAuthorization))
Set-JsonProperty -Object $gateDoc -Name "current_run_pointer_path" -Value $currentRunPointerPath
Set-JsonProperty -Object $gateDoc -Name "launch_record_path" -Value $launchRecordPath
Write-JsonAtomic -Object $gateDoc -Path $gatePath

$currentRunPointer = [ordered]@{
    schema = "active_run_pointer_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    manifest_path = $manifestPath
    output = [ordered]@{ path = $snapshotPath; kind = "file" }
    collector_pid = $null
    monitor_pid = $PID
    process_ids = @($PID)
    launch_record_path = $launchRecordPath
}
Write-JsonAtomic -Object $currentRunPointer -Path $currentRunPointerPath

Write-Host "[pit-universe] visible collect started in this terminal" -ForegroundColor Cyan
Write-Host "[pit-universe] run_id=$RunId"
Write-Host "[pit-universe] snapshots=$snapshotPath"
Write-Host "[pit-universe] manifest=$manifestPath"

$argsList = @(
    $modulePath,
    "--output-root", $OutputRoot,
    "--run-id", $RunId,
    "--duration-sec", ([string]$DurationSec),
    "--interval-sec", ([string]$IntervalSec),
    "--timeout-sec", ([string]$TimeoutSec),
    "--min-contracts-per-exchange", ([string]$MinContractsPerExchange),
    "--min-free-disk-gib", ([string]$MinFreeDiskGiB)
)
if ($ResumeIncomplete) {
    $argsList += "--resume"
}
$collector = Start-Process -FilePath $python -ArgumentList $argsList -NoNewWindow -PassThru
$gateDoc = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -Raw -LiteralPath $gatePath)
Set-JsonProperty -Object $gateDoc -Name "collector_pid" -Value $collector.Id
Set-JsonProperty -Object $gateDoc -Name "process_ids" -Value @($PID, $collector.Id)
Write-JsonAtomic -Object $gateDoc -Path $gatePath
$currentRunPointer.collector_pid = $collector.Id
$currentRunPointer.process_ids = @($PID, $collector.Id)
$currentRunPointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
Write-JsonAtomic -Object $currentRunPointer -Path $currentRunPointerPath
$collector.WaitForExit()
$exitCode = $collector.ExitCode

$gateDoc = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -Raw -LiteralPath $gatePath)
$manifest = if (Test-Path -LiteralPath $manifestPath) { ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -Raw -LiteralPath $manifestPath) } else { $null }
$manifestFinal = [bool]($manifest -and $manifest.final)
$completed = ($exitCode -eq 0 -and $manifestFinal)
$stopReason = if ($completed) { "completed" } elseif ($manifest -and $manifest.stop_reason) { [string]$manifest.stop_reason } else { "collector_exit_$exitCode" }
$completedDecision = if ($scheduleAuthorization) { "PIT_UNIVERSE_V2_NIGHT_SEGMENT_COMPLETED_SCHEDULE_REMAINS_ACTIVE" } else { "PIT_UNIVERSE_SNAPSHOT_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY" }
$completedNextStep = if ($scheduleAuthorization) { "Wait for the next approved visible PIT segment; preserve data embargo and do not run OOS evaluation/grid/probe/paper/live/API keys." } else { "Run PIT universe snapshot data-quality PlanOnly before replay/grid/live/API/paper-forward." }
Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty -Object $gateDoc -Name "status" -Value $(if ($completed) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" })
Set-JsonProperty -Object $gateDoc -Name "gate_status" -Value $(if ($completed) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" })
Set-JsonProperty -Object $gateDoc -Name "final" -Value $manifestFinal
Set-JsonProperty -Object $gateDoc -Name "collector_pid" -Value $null
Set-JsonProperty -Object $gateDoc -Name "stale_monitor_pid" -Value $PID
Set-JsonProperty -Object $gateDoc -Name "monitor_pid" -Value $null
Set-JsonProperty -Object $gateDoc -Name "process_ids" -Value @()
Set-JsonProperty -Object $gateDoc -Name "primary_output_complete" -Value (Test-Path -LiteralPath $snapshotPath)
Set-JsonProperty -Object $gateDoc -Name "expected_outputs_complete" -Value $completed
Set-JsonProperty -Object $gateDoc -Name "stop_reason" -Value $stopReason
Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $(if ($completed) { $completedDecision } else { "PIT_UNIVERSE_SNAPSHOT_COLLECT_STOPPED_INCOMPLETE" })
Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $(if ($completed) { $completedNextStep } else { "Resume visibly with -ResumeIncomplete and the same RunId after explicit user approval, or explicitly reject the incomplete dataset." })
Set-JsonProperty -Object $gateDoc -Name "resume_command" -Value $(if ($completed) { $null } else { $command })
Write-JsonAtomic -Object $gateDoc -Path $gatePath
$currentRunPointer.status = $(if ($completed) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" })
$currentRunPointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
$currentRunPointer.collector_pid = $null
$currentRunPointer.monitor_pid = $null
$currentRunPointer.process_ids = @()
Write-JsonAtomic -Object $currentRunPointer -Path $currentRunPointerPath

if ($exitCode -ne 0) {
    throw "pit_universe_snapshot_collector.py failed with exit code $exitCode"
}
