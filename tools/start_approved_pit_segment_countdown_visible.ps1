param(
    [Parameter(Mandatory = $true)][string]$SchedulePlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedSchedulePlanHash,
    [Parameter(Mandatory = $true)][string]$RunId,
    [int]$PollSec = 30,
    [switch]$PlanOnly,
    [switch]$PreflightOnly,
    [switch]$VisibleChild
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$visibleWrapper = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$autopilotChecker = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$postRun = Join-Path $repoRoot "tools\run_trading_mvp_pit_postrun.ps1"
$planCli = Join-Path $repoRoot "trading_mvp\src\night_schedule_plan.py"
$schedulePointerPath = Join-Path $repoRoot "docs\agent-log\trading-mvp-autopilot-schedule-pointer.json"
$metadataPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.countdown.json"
$launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.launch.json"
$postRunSummaryPath = Join-Path $repoRoot "docs\agent-log\run-gates\$RunId.postrun.json"
$globalWriterClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$globalWriterClaimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$globalWriterClaimCli = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"

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
        & $candidate -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    throw "No project Python is available. Set TRADING_MVP_PYTHON."
}

function Invoke-SegmentAuthorization {
    $output = @(& $script:python $planCli `
        "authorize-segment" `
        "--plan" $SchedulePlanPath `
        "--expected-plan-hash" $ExpectedSchedulePlanHash `
        "--run-id" $RunId 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $detail = @(
            $output |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ }
        ) | Select-Object -Last 1
        if (-not $detail) {
            $detail = "exit code $LASTEXITCODE"
        }
        throw "Hash-bound segment authorization failed: $detail"
    }
    $authorization = ConvertFrom-JsonPreserveDateStrings -InputJson $output
    if ([string]$authorization.verdict -ne "AUTHORIZED") {
        throw "Hash-bound segment authorization did not return AUTHORIZED."
    }
    return $authorization
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
        if (-not $toolPath -or $expectedSha -notmatch "^[0-9a-f]{64}$") {
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
        visible_wrapper = $visibleWrapper
    }
    foreach ($binding in $bindings.GetEnumerator()) {
        $entry = $runtimeTools.PSObject.Properties[$binding.Key].Value
        if (
            -not $entry -or
            [System.IO.Path]::GetFullPath([string]$entry.path) -ne
            [System.IO.Path]::GetFullPath([string]$binding.Value)
        ) {
            throw "Countdown runtime path is not the sealed $($binding.Key)."
        }
    }

    return @($observed)
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $tempPath = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

function New-GlobalMarketWriterClaim {
    $raw = @(& $script:python $globalWriterClaimCli `
        "claim" `
        "--path" $globalWriterClaimPath `
        "--run-id" $RunId `
        "--owner-pid" ([string]$PID) `
        "--owner-kind" "pit_countdown_visible_child" `
        "--plan-hash" $ExpectedSchedulePlanHash `
        "--output-namespace" ([string]$segment.output_dir) `
        "--terminal-pid" ([string]$PID) 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS_OR_FAILED: $(@($raw) -join ' ')"
    }
    $claim = ConvertFrom-JsonPreserveDateStrings -InputJson $raw
    if (
        [string]$claim.run_id -ne $RunId -or
        [int]$claim.owner_pid -ne $PID -or
        [string]$claim.ownership_token -notmatch '^[0-9a-f]{32}$'
    ) {
        throw "Global market-writer claim identity mismatch after atomic acquire."
    }
    return $claim
}

function Remove-GlobalMarketWriterClaim {
    param(
        [Parameter(Mandatory = $true)][string]$OwnershipToken,
        [Parameter(Mandatory = $true)][string]$FinalStatus
    )

    $raw = @(& $script:python $globalWriterClaimCli `
        "release" `
        "--path" $globalWriterClaimPath `
        "--run-id" $RunId `
        "--owner-pid" ([string]$PID) `
        "--ownership-token" $OwnershipToken `
        "--final-status" $FinalStatus `
        "--archive-dir" $globalWriterClaimArchiveDir 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Global market-writer claim release failed: $(@($raw) -join ' ')"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $raw
}

function Set-MetadataStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Message = ""
    )

    $script:metadata.status = $Status
    $script:metadata.message = $Message
    $script:metadata.updated_at = [DateTimeOffset]::Now.ToString("o")
    $script:metadata.countdown_pid = $PID
    Write-JsonAtomic -Object $script:metadata -Path $metadataPath
}

function Get-FreeDiskGiB {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $driveRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($driveRoot)) {
        throw "Cannot resolve drive root for output path: $Path"
    }
    $drive = [System.IO.DriveInfo]::new($driveRoot)
    if (-not $drive.IsReady) {
        throw "Output drive is not ready: $driveRoot"
    }
    return [Math]::Round($drive.AvailableFreeSpace / 1GB, 3)
}

function Get-OtherCountdownOwners {
    $scriptName = [System.IO.Path]::GetFileName($PSCommandPath)
    $scriptPattern = [regex]::Escape($scriptName)
    $runPattern = [regex]::Escape($RunId)
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $processById = @{}
    foreach ($process in $processes) {
        $processById[[int]$process.ProcessId] = $process
    }
    $excludedProcessIds = [System.Collections.Generic.HashSet[int]]::new()
    $cursorPid = [int]$PID
    while ($cursorPid -gt 0 -and $excludedProcessIds.Add($cursorPid)) {
        if (-not $processById.ContainsKey($cursorPid)) {
            break
        }
        $cursorPid = [int]$processById[$cursorPid].ParentProcessId
    }
    $owners = @(
        $processes |
        Where-Object {
            -not $excludedProcessIds.Contains([int]$_.ProcessId) -and
            [string]$_.CommandLine -match $scriptPattern -and
            [string]$_.CommandLine -match $runPattern
        } |
        ForEach-Object {
            [ordered]@{
                pid = [int]$_.ProcessId
                name = [string]$_.Name
                command_line = [string]$_.CommandLine
            }
        }
    )
    return $owners
}

function Invoke-RuntimePreflight {
    param(
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)]$Segment,
        [Parameter(Mandatory = $true)][int]$DurationSec,
        [Parameter(Mandatory = $true)][double]$MinFreeDiskGiB,
        [Parameter(Mandatory = $true)][string]$OutputRoot,
        [Parameter(Mandatory = $true)][DateTimeOffset]$NotBefore,
        [Parameter(Mandatory = $true)][DateTimeOffset]$ScheduledEnd,
        [Parameter(Mandatory = $true)][DateTimeOffset]$NotLater
    )

    $sealedRuntimeTools = @(Assert-SealedRuntimeTools -Plan $Plan)

    if (-not (Test-Path -LiteralPath $schedulePointerPath)) {
        throw "Dynamic PIT schedule pointer is missing: $schedulePointerPath"
    }
    $pointer = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $schedulePointerPath
    )
    $fullPlanPath = [System.IO.Path]::GetFullPath($SchedulePlanPath)
    if ([string]$pointer.status -ne "ACTIVE") {
        throw "Dynamic PIT schedule pointer is not ACTIVE."
    }
    if ([System.IO.Path]::GetFullPath([string]$pointer.plan_path) -ne $fullPlanPath) {
        throw "Dynamic PIT schedule pointer path mismatch."
    }
    if ([string]$pointer.plan_hash -ne $ExpectedSchedulePlanHash) {
        throw "Dynamic PIT schedule pointer hash mismatch."
    }

    $gateJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Active-run gate preflight failed with exit code $LASTEXITCODE."
    }
    $gate = ConvertFrom-JsonPreserveDateStrings -InputJson $gateJson
    $gateStatus = [string]$gate.status
    $gateRunId = [string]$gate.run_id
    $alreadyRunning = $gateStatus -eq "RUNNING" -and $gateRunId -eq $RunId
    $globalWriterClaim = $null
    if (Test-Path -LiteralPath $globalWriterClaimPath -PathType Leaf) {
        try {
            $existingClaim = ConvertFrom-JsonPreserveDateStrings -InputJson (
                Get-Content -Raw -LiteralPath $globalWriterClaimPath
            )
            $globalWriterClaim = [ordered]@{
                status = [string]$existingClaim.status
                run_id = [string]$existingClaim.run_id
                owner_pid = $existingClaim.owner_pid
                writer_pid = $existingClaim.writer_pid
                terminal_pid = $existingClaim.terminal_pid
            }
        } catch {
            $globalWriterClaim = [ordered]@{
                status = "UNREADABLE_FAIL_CLOSED"
                run_id = $null
                owner_pid = $null
                writer_pid = $null
                terminal_pid = $null
            }
        }
    }
    if ($gateStatus -eq "RUNNING" -and -not $alreadyRunning) {
        throw "Another run owns the active-run gate: run_id=$gateRunId."
    }
    if ($gateStatus -eq "STOPPED_INCOMPLETE") {
        throw "Active-run gate is STOPPED_INCOMPLETE for run_id=$gateRunId."
    }

    $autopilotJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $autopilotChecker -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot guard preflight failed with exit code $LASTEXITCODE."
    }
    $autopilot = ConvertFrom-JsonPreserveDateStrings -InputJson $autopilotJson
    $schedule = $autopilot.schedule_window
    if (-not $schedule) {
        throw "Autopilot guard did not expose an exact PIT schedule window."
    }
    if ([string]$schedule.classification -ne "PREAPPROVED_SHORT_SEGMENT") {
        throw "Autopilot schedule classification is not PREAPPROVED_SHORT_SEGMENT."
    }
    if ([string]$schedule.run_id -ne $RunId) {
        throw "Autopilot next segment mismatch: expected=$RunId observed=$($schedule.run_id)."
    }
    if ([System.IO.Path]::GetFullPath([string]$schedule.plan_path) -ne $fullPlanPath) {
        throw "Autopilot schedule plan path mismatch."
    }
    if ([string]$schedule.plan_hash -ne $ExpectedSchedulePlanHash) {
        throw "Autopilot schedule plan hash mismatch."
    }
    if ([string]$schedule.status -notin @("WAITING", "DUE")) {
        throw "Autopilot schedule status is not launchable: $($schedule.status)."
    }

    $now = [DateTimeOffset]::Now
    $earliestFinish = if ($now -gt $NotBefore) {
        $now.AddSeconds($DurationSec)
    } else {
        $NotBefore.AddSeconds($DurationSec)
    }
    if ($now -ge $NotLater -or $earliestFinish -gt $NotLater) {
        throw "Approved PIT segment cannot finish before its hard deadline."
    }
    if ($ScheduledEnd -gt $NotLater) {
        throw "Frozen scheduled end exceeds the hard deadline."
    }

    $otherOwners = @(Get-OtherCountdownOwners)
    $freeDiskGiB = Get-FreeDiskGiB -Path $OutputRoot
    if ($freeDiskGiB -lt $MinFreeDiskGiB) {
        throw "disk_space_below_threshold: free_gib=$freeDiskGiB required_gib=$MinFreeDiskGiB output_root=$OutputRoot"
    }

    if (-not $alreadyRunning) {
        if (Test-Path -LiteralPath $launchRecordPath) {
            throw "Immutable launch record already exists: $launchRecordPath"
        }
        if (Test-Path -LiteralPath ([string]$Segment.output_dir)) {
            throw "Segment output directory already exists: $($Segment.output_dir)"
        }
    }

    $etaSec = [Math]::Max(0, [Math]::Ceiling(($NotBefore - $now).TotalSeconds))
    $dueSoon = [string]$schedule.status -eq "DUE" -or $etaSec -le 300
    $paused = $autopilot.stop_new_actions -eq $true
    $status = if ($alreadyRunning) {
        "ALREADY_RUNNING"
    } elseif ($otherOwners.Count -gt 0) {
        "COUNTDOWN_ALREADY_RUNNING"
    } elseif ($globalWriterClaim) {
        "GLOBAL_WRITER_CLAIM_EXISTS"
    } elseif ($paused) {
        [string]$autopilot.status
    } elseif ($dueSoon) {
        "READY_TO_LAUNCH"
    } else {
        "READY_NOT_DUE"
    }

    return [ordered]@{
        schema = "approved_pit_visible_countdown_preflight_v1"
        status = $status
        checks_passed = $true
        launch_allowed_now = [bool](
            -not $alreadyRunning -and
            $otherOwners.Count -eq 0 -and
            -not $globalWriterClaim -and
            -not $paused -and
            $dueSoon
        )
        run_id = $RunId
        plan_path = $fullPlanPath
        plan_hash = $ExpectedSchedulePlanHash
        sealed_runtime_tools_verified = $sealedRuntimeTools.Count
        sealed_runtime_tool_names = @($sealedRuntimeTools | ForEach-Object { $_.name })
        schedule_status = [string]$schedule.status
        eta_sec = [long]$etaSec
        not_before = $NotBefore.ToString("o")
        scheduled_end = $ScheduledEnd.ToString("o")
        hard_deadline = $NotLater.ToString("o")
        output_dir = [string]$Segment.output_dir
        free_disk_gib = $freeDiskGiB
        min_free_disk_gib = $MinFreeDiskGiB
        gate_status = $gateStatus
        gate_run_id = $gateRunId
        autopilot_status = [string]$autopilot.status
        autopilot_decision = [string]$autopilot.decision
        weekly_remaining_percent = [double]$autopilot.usage.remaining_percent
        other_countdown_owners = $otherOwners
        global_market_writer_claim = $globalWriterClaim
        global_market_writer_claim_path = $globalWriterClaimPath
        observed_at = $now.ToString("o")
        side_effects = "NO_RUN_OR_OUTPUT_WRITES"
    }
}

if ($PlanOnly -and $PreflightOnly) {
    throw "PlanOnly and PreflightOnly are mutually exclusive."
}
if ($PollSec -lt 5 -or $PollSec -gt 300) {
    throw "PollSec must be in [5, 300]."
}
if (-not (Test-Path -LiteralPath $SchedulePlanPath)) {
    throw "Schedule plan is missing: $SchedulePlanPath"
}
if (-not (Test-Path -LiteralPath $visibleWrapper)) {
    throw "Visible PIT wrapper is missing: $visibleWrapper"
}
if (-not (Test-Path -LiteralPath $autopilotChecker)) {
    throw "Autopilot usage guard is missing: $autopilotChecker"
}
if (-not (Test-Path -LiteralPath $postRun)) {
    throw "PIT post-run orchestrator is missing: $postRun"
}
if (-not (Test-Path -LiteralPath $planCli)) {
    throw "Night schedule authorization CLI is missing: $planCli"
}
if (-not (Test-Path -LiteralPath $globalWriterClaimCli)) {
    throw "Global market-writer claim CLI is missing: $globalWriterClaimCli"
}

$python = Resolve-ProjectPython
$plan = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -Raw -LiteralPath $SchedulePlanPath)
$initialSealedRuntimeTools = @(Assert-SealedRuntimeTools -Plan $plan)
$initialAuthorization = Invoke-SegmentAuthorization
$segments = @($plan.segments | Where-Object { [string]$_.run_id -eq $RunId })
if ($segments.Count -ne 1) {
    throw "Expected exactly one segment for RunId=$RunId, observed=$($segments.Count)."
}
$segment = $segments[0]
$executionConfig = $plan.sealed_schedule.execution_config
if (-not $executionConfig) {
    throw "Frozen execution_config is missing from schedule plan."
}

$durationSec = [int]$segment.duration_sec
$intervalSec = [int]$segment.interval_sec
$timeoutSec = [int]$executionConfig.timeout_sec
$minContracts = [int]$executionConfig.min_contracts_per_exchange
$minFreeDiskGiB = [double]$executionConfig.min_free_disk_gib
$outputRoot = [string]$plan.output_root
$notBeforeText = [string]$segment.start_local
$notLaterText = [string]$segment.hard_deadline_local
$notBefore = ConvertTo-DateTimeOffsetInvariant -Value $notBeforeText
$notLater = ConvertTo-DateTimeOffsetInvariant -Value $notLaterText
$scheduledEnd = ConvertTo-DateTimeOffsetInvariant -Value ([string]$segment.end_local)

if ($durationSec -lt 1 -or $durationSec -gt 10800) {
    throw "Frozen duration_sec is outside [1, 10800]: $durationSec"
}
if ($intervalSec -lt 1 -or $intervalSec -gt $durationSec) {
    throw "Frozen interval_sec is invalid: $intervalSec"
}
if ([DateTimeOffset]::Now -ge $notLater) {
    throw "Approved segment deadline has already passed: $notLaterText"
}

$validationArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $visibleWrapper,
    "-DurationSec", [string]$durationSec,
    "-IntervalSec", [string]$intervalSec,
    "-TimeoutSec", [string]$timeoutSec,
    "-MinContractsPerExchange", [string]$minContracts,
    "-OutputRoot", $outputRoot,
    "-RunId", $RunId,
    "-MinFreeDiskGiB", [string]$minFreeDiskGiB,
    "-ApprovedNotBefore", $notBeforeText,
    "-ApprovedNotLaterThan", $notLaterText,
    "-SchedulePlanPath", $SchedulePlanPath,
    "-ExpectedSchedulePlanHash", $ExpectedSchedulePlanHash,
    "-PlanOnly", "-Json"
)
$validationOutput = & pwsh @validationArgs
if ($LASTEXITCODE -ne 0) {
    throw "Guarded PIT PlanOnly validation failed with exit code $LASTEXITCODE."
}
$validatedPlan = ConvertFrom-JsonPreserveDateStrings -InputJson $validationOutput
if ([string]$validatedPlan.run_id -ne $RunId -or -not $validatedPlan.approved_night_schedule) {
    throw "Guarded PIT PlanOnly validation did not bind the approved segment."
}

$metadata = [ordered]@{
    schema = "approved_pit_visible_countdown_v1"
    status = "PLANNED"
    message = ""
    run_id = $RunId
    schedule_plan_path = [System.IO.Path]::GetFullPath($SchedulePlanPath)
    expected_schedule_plan_hash = $ExpectedSchedulePlanHash
    output_root = $outputRoot
    output_dir = [string]$segment.output_dir
    manifest_path = Join-Path ([string]$segment.output_dir) "manifest.json"
    not_before = $notBeforeText
    scheduled_end = $scheduledEnd.ToString("o")
    hard_deadline = $notLaterText
    duration_sec = $durationSec
    interval_sec = $intervalSec
    poll_sec = $PollSec
    visible_terminal = $true
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    global_market_writer_claim_path = $globalWriterClaimPath
    sealed_runtime_tools_verified = $initialSealedRuntimeTools.Count
    countdown_pid = $PID
    created_at = [DateTimeOffset]::Now.ToString("o")
    updated_at = [DateTimeOffset]::Now.ToString("o")
}

if ($PlanOnly) {
    $metadata.status = "PLAN_VALIDATED"
    $metadata | ConvertTo-Json -Depth 16
    exit 0
}

$runtimePreflight = Invoke-RuntimePreflight `
    -Plan $plan `
    -Segment $segment `
    -DurationSec $durationSec `
    -MinFreeDiskGiB $minFreeDiskGiB `
    -OutputRoot $outputRoot `
    -NotBefore $notBefore `
    -ScheduledEnd $scheduledEnd `
    -NotLater $notLater
if ($PreflightOnly) {
    $runtimePreflight | ConvertTo-Json -Depth 16
    exit 0
}
if ([string]$runtimePreflight.status -in @("ALREADY_RUNNING", "COUNTDOWN_ALREADY_RUNNING")) {
    Write-Host "[pit-countdown] $($runtimePreflight.status); no duplicate launched" -ForegroundColor Yellow
    exit 0
}
if ([string]$runtimePreflight.status -eq "GLOBAL_WRITER_CLAIM_EXISTS") {
    throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS: explicit stale/live owner reconciliation is required."
}
if ($runtimePreflight.autopilot_status -like "PAUSED*") {
    Write-Host "[pit-countdown] paused by autopilot guard: $($runtimePreflight.autopilot_decision)" -ForegroundColor Yellow
    exit 0
}
if (-not $runtimePreflight.launch_allowed_now) {
    throw "Approved segment is not DUE and does not start within five minutes: eta_sec=$($runtimePreflight.eta_sec)."
}

if (-not $VisibleChild) {
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $childArgs = @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath,
        "-SchedulePlanPath", $SchedulePlanPath,
        "-ExpectedSchedulePlanHash", $ExpectedSchedulePlanHash,
        "-RunId", $RunId,
        "-PollSec", [string]$PollSec,
        "-VisibleChild"
    )
    $terminal = Start-Process `
        -FilePath $pwsh `
        -ArgumentList $childArgs `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal `
        -PassThru

    $ownershipDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    $ownedMetadata = $null
    while ([DateTimeOffset]::UtcNow -lt $ownershipDeadline) {
        if ($terminal.HasExited) {
            throw "Visible PIT terminal exited before claiming the countdown."
        }
        if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
            try {
                $candidateMetadata = ConvertFrom-JsonPreserveDateStrings -InputJson (
                    Get-Content -Raw -LiteralPath $metadataPath
                )
                if ([int]$candidateMetadata.countdown_pid -eq $terminal.Id) {
                    if ([string]$candidateMetadata.status -eq "FAILED") {
                        throw "Visible PIT terminal failed: $($candidateMetadata.message)"
                    }
                    if ([string]$candidateMetadata.status -ne "PLANNED") {
                        $ownedMetadata = $candidateMetadata
                        break
                    }
                }
            } catch {
                if ($_.Exception.Message -like "Visible PIT terminal failed:*") {
                    throw
                }
            }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ownedMetadata) {
        throw "Visible PIT terminal did not claim the exact countdown within 30 seconds."
    }

    [ordered]@{
        schema = "approved_pit_visible_terminal_launch_v1"
        status = "VISIBLE_TERMINAL_LAUNCHED"
        run_id = $RunId
        schedule_plan_path = [System.IO.Path]::GetFullPath($SchedulePlanPath)
        schedule_plan_hash = $ExpectedSchedulePlanHash
        visible_terminal_pid = $terminal.Id
        terminal_ownership_verified = $true
        child_status = [string]$ownedMetadata.status
        countdown_metadata_path = $metadataPath
        launched_at = [DateTimeOffset]::Now.ToString("o")
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
    } | ConvertTo-Json -Depth 16
    exit 0
}

$globalWriterClaimToken = $null
$globalWriterClaimReleased = $false
try {
    try {
        $host.UI.RawUI.WindowTitle = "trading_mvp PIT countdown - $RunId"
    } catch {
        # Non-interactive hosts can lack RawUI; writer authorization stays fail-closed.
    }
    if (Test-Path -LiteralPath $launchRecordPath) {
        throw "Immutable launch record already exists: $launchRecordPath"
    }
    if (Test-Path -LiteralPath ([string]$segment.output_dir)) {
        throw "Segment output directory already exists: $($segment.output_dir)"
    }

    Set-MetadataStatus -Status "WAITING_FOR_APPROVED_WINDOW" -Message "Visible countdown owns this scheduled segment."
    Write-Host "[pit-countdown] approved visible segment" -ForegroundColor Cyan
    Write-Host "[pit-countdown] run_id=$RunId"
    Write-Host "[pit-countdown] starts=$notBeforeText"
    Write-Host "[pit-countdown] expected_finish=$($scheduledEnd.ToString('o'))"
    Write-Host "[pit-countdown] output=$($segment.output_dir)"

    while ($true) {
        $now = [DateTimeOffset]::Now
        if ($now -ge $notLater) {
            throw "Approved segment deadline passed before launch."
        }

        $gateJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
        if ($LASTEXITCODE -ne 0) {
            throw "Active-run gate check failed with exit code $LASTEXITCODE."
        }
        $gate = ConvertFrom-JsonPreserveDateStrings -InputJson $gateJson
        $gateStatus = [string]$gate.status
        $gateRunId = [string]$gate.run_id

        if ($gateStatus -eq "STOPPED_INCOMPLETE") {
            throw "Active-run gate is STOPPED_INCOMPLETE for run_id=$gateRunId."
        }
        if ($gateStatus -eq "RUNNING" -and $gateRunId -eq $RunId) {
            Set-MetadataStatus -Status "EXISTING_RUN_DETECTED" -Message "Another visible owner started the same approved segment."
            Write-Host "[pit-countdown] same run already started; no duplicate launched" -ForegroundColor Yellow
            exit 0
        }
        if ($gateStatus -eq "RUNNING" -and $now -ge $notBefore) {
            throw "Approved window opened while another run owns the gate: run_id=$gateRunId."
        }

        $remainingSec = [Math]::Max(0, [Math]::Ceiling(($notBefore - $now).TotalSeconds))
        if ($remainingSec -le 0) {
            break
        }

        $eta = [TimeSpan]::FromSeconds($remainingSec).ToString("hh\:mm\:ss")
        $gateSummary = if ($gateStatus -eq "RUNNING") { "blocked_by=$gateRunId" } else { "gate=$gateStatus" }
        Write-Host "[pit-countdown] now=$($now.ToString('HH:mm:ss')) eta=$eta $gateSummary"
        Set-MetadataStatus -Status "WAITING_FOR_APPROVED_WINDOW" -Message "eta_sec=$remainingSec; $gateSummary"
        Start-Sleep -Seconds ([Math]::Min($PollSec, [int]$remainingSec))
    }

    Set-MetadataStatus -Status "STARTING_GUARDED_COLLECT" -Message "Approved window opened; revalidating and starting collector."
    Write-Host "[pit-countdown] approved window opened; starting guarded collector" -ForegroundColor Green

    $windowAuthorization = Invoke-SegmentAuthorization
    Write-Host "[pit-countdown] segment authorization revalidated at window open" -ForegroundColor Green

    $launchPreflight = Invoke-RuntimePreflight `
        -Plan $plan `
        -Segment $segment `
        -DurationSec $durationSec `
        -MinFreeDiskGiB $minFreeDiskGiB `
        -OutputRoot $outputRoot `
        -NotBefore $notBefore `
        -ScheduledEnd $scheduledEnd `
        -NotLater $notLater
    if ([string]$launchPreflight.status -in @("ALREADY_RUNNING", "COUNTDOWN_ALREADY_RUNNING")) {
        Set-MetadataStatus -Status ([string]$launchPreflight.status) -Message "Fresh launch preflight found another exact owner."
        Write-Host "[pit-countdown] $($launchPreflight.status); no duplicate launched" -ForegroundColor Yellow
        exit 0
    }
    if ([string]$launchPreflight.status -eq "GLOBAL_WRITER_CLAIM_EXISTS") {
        throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS: explicit stale/live owner reconciliation is required."
    }
    if ($launchPreflight.autopilot_status -like "PAUSED*") {
        Set-MetadataStatus -Status ([string]$launchPreflight.autopilot_status) -Message ([string]$launchPreflight.autopilot_decision)
        Write-Host "[pit-countdown] collector paused by weekly usage guard: $($launchPreflight.autopilot_decision)" -ForegroundColor Yellow
        exit 0
    }
    if (
        [string]$launchPreflight.schedule_status -ne "DUE" -or
        -not $launchPreflight.launch_allowed_now
    ) {
        throw "Fresh launch preflight no longer authorizes the exact DUE segment: status=$($launchPreflight.status) schedule_status=$($launchPreflight.schedule_status)."
    }
    Write-Host "[pit-countdown] sealed-runtime/pointer/guard/disk/duplicate preflight revalidated at launch" -ForegroundColor Green

    $globalWriterClaim = New-GlobalMarketWriterClaim
    $globalWriterClaimToken = [string]$globalWriterClaim.ownership_token
    $script:metadata["global_market_writer_claim_owner_pid"] = $PID
    $script:metadata["global_market_writer_claim_acquired_at_utc"] = [string]$globalWriterClaim.claimed_at_utc
    Set-MetadataStatus -Status "STARTING_GUARDED_COLLECT" -Message "Global one-writer claim acquired; starting sealed wrapper."

    & pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleWrapper `
        -DurationSec $durationSec `
        -IntervalSec $intervalSec `
        -TimeoutSec $timeoutSec `
        -MinContractsPerExchange $minContracts `
        -OutputRoot $outputRoot `
        -RunId $RunId `
        -MinFreeDiskGiB $minFreeDiskGiB `
        -ApprovedNotBefore $notBeforeText `
        -ApprovedNotLaterThan $notLaterText `
        -SchedulePlanPath $SchedulePlanPath `
        -ExpectedSchedulePlanHash $ExpectedSchedulePlanHash `
        -ConfirmedPitUniverseSnapshotCollect
    $collectorExitCode = $LASTEXITCODE
    if ($collectorExitCode -ne 0) {
        throw "Guarded visible collector failed with exit code $collectorExitCode."
    }

    $collectorGateJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Post-collector active-run gate check failed with exit code $LASTEXITCODE."
    }
    $collectorGate = ConvertFrom-JsonPreserveDateStrings -InputJson $collectorGateJson
    if ([string]$collectorGate.status -ne "READY_FOR_POSTPROCESS") {
        throw "Guarded visible collector returned without READY_FOR_POSTPROCESS: status=$($collectorGate.status)."
    }
    if ([string]$collectorGate.run_id -ne $RunId) {
        throw "Guarded visible collector returned a mismatched gate run_id=$($collectorGate.run_id)."
    }

    $releasedClaim = Remove-GlobalMarketWriterClaim `
        -OwnershipToken $globalWriterClaimToken `
        -FinalStatus "READY_FOR_POSTPROCESS"
    $globalWriterClaimReleased = $true
    $globalWriterClaimToken = $null
    $script:metadata["global_market_writer_claim_archive_path"] = [string]$releasedClaim.archive_path

    Set-MetadataStatus -Status "COLLECTOR_FINISHED" -Message "Guarded collector returned successfully."
    Write-Host "[pit-countdown] collector finished successfully" -ForegroundColor Green

    Set-MetadataStatus -Status "POSTRUN_RUNNING" -Message "Technical quality and deterministic continuation are running."
    $postRunStartedAt = [DateTimeOffset]::UtcNow
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $postRun `
        -SchedulePlanPath $SchedulePlanPath `
        -ExpectedSchedulePlanHash $ExpectedSchedulePlanHash `
        -RunId $RunId `
        -MaxRuntimeSec 1800
    if ($LASTEXITCODE -ne 0) {
        throw "PIT post-run failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $postRunSummaryPath -PathType Leaf)) {
        throw "PIT post-run returned without its durable summary: $postRunSummaryPath"
    }
    $postRunSummary = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $postRunSummaryPath -Raw
    )
    if (
        [string]$postRunSummary.schema -ne "trading_mvp_pit_postrun_v1" -or
        [string]$postRunSummary.run_id -ne $RunId -or
        [string]$postRunSummary.schedule_plan_hash -ne $ExpectedSchedulePlanHash -or
        [System.IO.Path]::GetFullPath([string]$postRunSummary.schedule_plan_path) -ne
        [System.IO.Path]::GetFullPath($SchedulePlanPath)
    ) {
        throw "PIT post-run durable summary identity or schedule binding mismatch."
    }
    $postRunCreatedAt = ConvertTo-DateTimeOffsetInvariant -Value ([string]$postRunSummary.created_at)
    if ($postRunCreatedAt.ToUniversalTime() -lt $postRunStartedAt.AddSeconds(-5)) {
        throw "PIT post-run durable summary is stale."
    }
    if (
        -not [string]$postRunSummary.decision -or
        -not [string]$postRunSummary.next_allowed_action -or
        $postRunSummary.returns_read -ne $false -or
        $postRunSummary.pnl_read -ne $false -or
        $postRunSummary.oos_run -ne $false -or
        $postRunSummary.grid_search -ne $false -or
        $postRunSummary.live_orders -ne $false -or
        $postRunSummary.private_api_keys -ne $false
    ) {
        throw "PIT post-run durable summary violated its decision or data embargo contract."
    }

    $script:metadata["postrun_summary_path"] = $postRunSummaryPath
    $script:metadata["postrun_summary_sha256"] = (
        Get-FileHash -LiteralPath $postRunSummaryPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $script:metadata["postrun_decision"] = [string]$postRunSummary.decision
    $script:metadata["postrun_next_allowed_action"] = [string]$postRunSummary.next_allowed_action
    $postRunDeferredActions = @(
        "wait_for_fresh_weekly_quota_above_15_percent_then_retry_postrun",
        "run_train_feasibility_after_weekly_quota_reset",
        "refresh_horizon_after_weekly_quota_reset_then_request_exact_schedule_approval"
    )
    $postRunDeferred = (
        [string]$postRunSummary.decision -like "PAUSED*" -or
        [string]$postRunSummary.next_allowed_action -in $postRunDeferredActions
    )
    if ($postRunDeferred) {
        Set-MetadataStatus `
            -Status "POSTRUN_DEFERRED" `
            -Message "Post-run deferred without bypass: decision=$($postRunSummary.decision); next=$($postRunSummary.next_allowed_action)."
        Write-Host "[pit-countdown] guarded post-run deferred: $($postRunSummary.decision)" -ForegroundColor Yellow
    } else {
        Set-MetadataStatus `
            -Status "POSTRUN_FINISHED" `
            -Message "Collector and guarded post-run completed: decision=$($postRunSummary.decision)."
        Write-Host "[pit-countdown] guarded post-run finished: $($postRunSummary.decision)" -ForegroundColor Green
    }
} catch {
    $failureMessage = $_.Exception.Message
    if ($globalWriterClaimToken -and -not $globalWriterClaimReleased) {
        try {
            $failureGateJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
            $failureGate = if ($LASTEXITCODE -eq 0) {
                ConvertFrom-JsonPreserveDateStrings -InputJson $failureGateJson
            } else {
                $null
            }
            if (
                $failureGate -and
                [string]$failureGate.status -eq "RUNNING" -and
                [string]$failureGate.run_id -eq $RunId
            ) {
                $failureMessage += " Global writer claim retained fail-closed because the exact gate is still RUNNING."
            } else {
                $terminalStatus = if (
                    $failureGate -and
                    [string]$failureGate.run_id -eq $RunId -and
                    [string]$failureGate.status -eq "STOPPED_INCOMPLETE"
                ) { "STOPPED_INCOMPLETE" } else { "NOT_STARTED" }
                $releasedClaim = Remove-GlobalMarketWriterClaim `
                    -OwnershipToken $globalWriterClaimToken `
                    -FinalStatus $terminalStatus
                $globalWriterClaimReleased = $true
                $globalWriterClaimToken = $null
                $script:metadata["global_market_writer_claim_archive_path"] = [string]$releasedClaim.archive_path
            }
        } catch {
            $failureMessage += " Global writer claim release reconciliation failed: $($_.Exception.Message)"
        }
    }
    Set-MetadataStatus -Status "FAILED" -Message $failureMessage
    Write-Host "[pit-countdown] FAILED: $failureMessage" -ForegroundColor Red
    throw
}
