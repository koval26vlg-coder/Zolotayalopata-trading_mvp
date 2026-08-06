[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [string]$RunId = "",
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1, 5400)][int]$MaxRuntimeSec = 1200,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [ValidateRange(0, 100000)][double]$MinimumFreeGb = 5,
    [string]$ApprovedNotBefore = "",
    [string]$ApprovedNotLaterThan = "",
    [switch]$ConfirmedPublicHistoryCollect,
    [switch]$ContinueToTrainPostprocess,
    [string]$TrainPostprocessOutputRoot = "",
    [ValidateRange(1, 1800)][int]$TrainPostprocessMaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$TrainPostprocessHoldOpenSec = 60,
    [switch]$Resume,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
$Validator = Join-Path $ProjectRoot "trading_mvp\src\historical_basis_v2.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
$TrainPostprocessWrapper = Join-Path $ProjectRoot "tools\start_historical_basis_v2_train_postprocess_visible.ps1"
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path (Split-Path -Parent $GatePath) "current-run.json"
}
if (-not $RunId) {
    $RunId = "basis_v2_history_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.visible.log"
}

function Set-ObjectProperty {
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

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            & $candidate -c "import requests" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return [System.IO.Path]::GetFullPath($candidate)
            }
        } catch { }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        try {
            & $command.Source -c "import requests" 2>$null
            if ($LASTEXITCODE -eq 0) { return $command.Source }
        } catch { }
    }
    throw "Python runtime with requests is required. Set TRADING_MVP_PYTHON."
}

function ConvertTo-DateTimeOffsetInvariant {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [DateTimeOffset]::Parse(
        $Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
}

function Get-ApprovalWindow {
    param([switch]$AllowDefaults)
    $now = [DateTimeOffset]::Now
    if (-not $ApprovedNotBefore) {
        if (-not $AllowDefaults) { throw "ApprovedNotBefore is required for an actual collect." }
        $notBefore = $now
    } else {
        $notBefore = ConvertTo-DateTimeOffsetInvariant -Value $ApprovedNotBefore
    }
    if (-not $ApprovedNotLaterThan) {
        if (-not $AllowDefaults) { throw "ApprovedNotLaterThan is required for an actual collect." }
        $notLaterThan = $notBefore.AddSeconds($MaxRuntimeSec)
    } else {
        $notLaterThan = ConvertTo-DateTimeOffsetInvariant -Value $ApprovedNotLaterThan
    }
    if ($notLaterThan -le $notBefore) {
        throw "ApprovedNotLaterThan must be after ApprovedNotBefore."
    }
    return [pscustomobject]@{
        not_before = $notBefore
        not_later_than = $notLaterThan
    }
}

function Invoke-PlanValidation {
    $python = Resolve-Python
    $env:TRADING_MVP_PYTHON = $python
    $json = & $python $Validator validate-plan --plan $PlanPath --expected-plan-hash $ExpectedPlanHash
    if ($LASTEXITCODE -ne 0) {
        throw "Historical basis v2 plan validation failed with exit code $LASTEXITCODE."
    }
    $validation = (@($json) -join [Environment]::NewLine) | ConvertFrom-Json
    if ([string]$validation.plan_hash -ne $ExpectedPlanHash) {
        throw "Validated plan hash does not match ExpectedPlanHash."
    }
    return $validation
}

function Get-GateState {
    if (-not (Test-Path -LiteralPath $GatePath)) {
        throw "Active run gate is missing: $GatePath"
    }
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $json = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Active run gate check failed with exit code $LASTEXITCODE."
    }
    return ((@($json) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Assert-GateOpen {
    param([Parameter(Mandatory = $true)]$Gate)
    $status = if ($Gate.gate_status) { [string]$Gate.gate_status } else { [string]$Gate.status }
    if ($status -eq "RUNNING") {
        throw "History collect blocked by active gate status=RUNNING, run_id=$($Gate.run_id)."
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before starting a history collect."
    }
}

function Get-FreeGb {
    param([Parameter(Mandatory = $true)][string]$Path)
    $root = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($Path))
    if (-not $root) { throw "Cannot resolve filesystem root for $Path" }
    $driveName = $root.TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName -ErrorAction Stop
    return [Math]::Round($drive.Free / 1GB, 3)
}

function Assert-NoWriterLease {
    $lease = Join-Path $OutputRoot ".historical-basis-v2-writer.lock"
    if (Test-Path -LiteralPath $lease) {
        throw "Historical basis v2 writer lease already exists: $lease"
    }
}

function Assert-NoPitScheduleOverlap {
    param([Parameter(Mandatory = $true)][DateTimeOffset]$Deadline)
    $gateDocument = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
    $schedule = $gateDocument.approved_night_schedule
    if (-not $schedule -or [string]$schedule.status -ne "ACTIVE") { return }
    $schedulePath = [string]$schedule.plan_path
    if (-not $schedulePath -or -not (Test-Path -LiteralPath $schedulePath)) {
        throw "Approved PIT schedule pointer is active but its plan is unavailable."
    }
    $schedulePlan = Get-Content -LiteralPath $schedulePath -Raw | ConvertFrom-Json
    $now = [DateTimeOffset]::Now
    $nextStart = @(
        $schedulePlan.segments |
            ForEach-Object { ConvertTo-DateTimeOffsetInvariant -Value ([string]$_.start_local) } |
            Where-Object { $_ -gt $now } |
            Sort-Object |
            Select-Object -First 1
    )[0]
    if ($nextStart -and $Deadline -ge $nextStart.AddMinutes(-5)) {
        throw "History collect deadline overlaps the protected PIT schedule window at $($nextStart.ToString('o'))."
    }
}

function Set-OwnedGateFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Reason,
        [Parameter(Mandatory = $true)][string]$Failure
    )
    foreach ($path in @($GatePath, $CurrentRunPath) | Select-Object -Unique) {
        if (Test-Path -LiteralPath $path) {
            $document = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            $status = if ($document.gate_status) { [string]$document.gate_status } else { [string]$document.status }
            if ($status -eq "RUNNING" -and [string]$document.run_id -ne $RunId) {
                continue
            }
        } else {
            $document = [pscustomobject]@{ schema = "active_run_gate_v2"; project = "trading_mvp" }
        }
        Set-ObjectProperty -Object $document -Name "run_id" -Value $RunId
        Set-ObjectProperty -Object $document -Name "status" -Value "STOPPED_INCOMPLETE"
        Set-ObjectProperty -Object $document -Name "gate_status" -Value "STOPPED_INCOMPLETE"
        Set-ObjectProperty -Object $document -Name "final" -Value $false
        Set-ObjectProperty -Object $document -Name "errors" -Value 1
        Set-ObjectProperty -Object $document -Name "stop_reason" -Value $Reason
        Set-ObjectProperty -Object $document -Name "failure" -Value $Failure
        Set-ObjectProperty -Object $document -Name "manifest_path" -Value $ManifestPath
        Set-ObjectProperty -Object $document -Name "output_path" -Value $RunDirectory
        Set-ObjectProperty -Object $document -Name "replay_allowed" -Value $false
        Set-ObjectProperty -Object $document -Name "grid_allowed" -Value $false
        Set-ObjectProperty -Object $document -Name "updated_at" -Value ([DateTimeOffset]::Now.ToString("o"))
        Write-JsonAtomic -Path $path -Value $document
    }
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not (Test-Path -LiteralPath $LaunchRecordPath)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-ObjectProperty -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "Historical basis v2 plan is missing: $PlanPath"
}
$PlanPath = (Resolve-Path -LiteralPath $PlanPath).Path
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
if (-not $TrainPostprocessOutputRoot) {
    $TrainPostprocessOutputRoot = Join-Path $OutputRoot "postprocess"
}
$TrainPostprocessOutputRoot = [System.IO.Path]::GetFullPath($TrainPostprocessOutputRoot)
if ($ContinueToTrainPostprocess -and -not (Test-Path -LiteralPath $TrainPostprocessWrapper)) {
    throw "Train postprocess wrapper is missing: $TrainPostprocessWrapper"
}
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$RunDirectory = Join-Path (Join-Path $OutputRoot "runs") $RunId
$ManifestPath = Join-Path $RunDirectory "manifest.json"
$validation = Invoke-PlanValidation

if ($Worker) {
    if (-not $WorkerToken) { throw "WorkerToken is required in worker mode." }
    if (-not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Worker launch record is missing: $LaunchRecordPath"
    }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) {
        throw "Worker token mismatch."
    }
    if (
        [string]$launch.run_id -ne $RunId -or
        [string]$launch.plan_hash -ne $ExpectedPlanHash -or
        [System.IO.Path]::GetFullPath([string]$launch.plan_path) -ne $PlanPath -or
        [System.IO.Path]::GetFullPath([string]$launch.python_runtime) -ne $env:TRADING_MVP_PYTHON
    ) {
        throw "Worker launch record does not match the requested run."
    }
    $window = Get-ApprovalWindow
    $now = [DateTimeOffset]::Now
    if ($now -lt $window.not_before -or $now -ge $window.not_later_than) {
        throw "Worker started outside the explicitly approved window."
    }
    $env:PYTHONUNBUFFERED = "1"
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp basis-v2 history - $RunId" } catch { }
    Update-LaunchRecord -Values @{
        status = "RUNNING"
        worker_pid = $PID
        worker_started_at = $now.ToString("o")
    }
    Write-Host "trading_mvp basis-v2 visible public history collect" -ForegroundColor Cyan
    Write-Host "run_id=$RunId"
    Write-Host "plan_hash=$ExpectedPlanHash"
    Write-Host "hard_deadline=$($window.not_later_than.ToString('o'))"
    Write-Host "manifest=$ManifestPath"
    $exitCode = 0
    try {
        $runParameters = @{
            Action = "fast-edge-basis-v2-history-collect"
            PlanPath = $PlanPath
            ExpectedPlanHash = $ExpectedPlanHash
            RunId = $RunId
            OutputPath = $OutputRoot
            ActiveRunGatePath = $GatePath
            MaxRuntimeSec = $MaxRuntimeSec
        }
        if ($Resume) { $runParameters.Resume = $true }
        & $RunMvp @runParameters 2>&1 | Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE) { $exitCode = [int]$LASTEXITCODE }
        if ($exitCode -ne 0) {
            throw "run_mvp exited with code $exitCode"
        }
        if (-not (Test-Path -LiteralPath $ManifestPath)) {
            throw "Collector exited without manifest: $ManifestPath"
        }
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        if (
            [string]$manifest.plan_hash -ne $ExpectedPlanHash -or
            [string]$manifest.run_id -ne $RunId
        ) {
            throw "Collector manifest is not bound to the approved run."
        }
        if ($manifest.final -ne $true -or [string]$manifest.status -ne "READY_FOR_POSTPROCESS") {
            Update-LaunchRecord -Values @{
                status = "STOPPED_INCOMPLETE"
                completed_at = ([DateTimeOffset]::Now.ToString("o"))
                manifest_path = $ManifestPath
                worker_exit_code = 2
            }
            Write-Host "STOPPED_INCOMPLETE: completed=$($manifest.completed_items)/$($manifest.expected_items) errors=$($manifest.error_count)" -ForegroundColor Red
            if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
            exit 2
        }
        Update-LaunchRecord -Values @{
            status = "COMPLETED"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            manifest_path = $ManifestPath
            manifest_hash = [string]$manifest.manifest_hash
            worker_exit_code = 0
        }
        Write-Host "READY_FOR_POSTPROCESS: completed=$($manifest.completed_items)/$($manifest.expected_items)" -ForegroundColor Green
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        $failurePath = Join-Path (Split-Path -Parent $LogPath) "$RunId.wrapper-failure.json"
        Write-JsonAtomic -Path $failurePath -Value ([ordered]@{
            schema = "trading_mvp_basis_v2_visible_failure_v1"
            run_id = $RunId
            final = $false
            error = $message
            plan_path = $PlanPath
            plan_hash = $ExpectedPlanHash
            manifest_path = $ManifestPath
            created_at = [DateTimeOffset]::Now.ToString("o")
        })
        try { Set-OwnedGateFailure -Reason "basis_v2_visible_worker_failed" -Failure $message } catch { }
        Update-LaunchRecord -Values @{
            status = "STOPPED_INCOMPLETE"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            failure = $message
            failure_path = $failurePath
            worker_exit_code = 1
        }
        Write-Host "FAILED: $message" -ForegroundColor Red
        Write-Host "failure_artifact=$failurePath"
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Get-GateState
Assert-GateOpen -Gate $gate
$window = Get-ApprovalWindow -AllowDefaults
$freeGb = Get-FreeGb -Path $OutputRoot
$pipelineRuntimeCapSec = $MaxRuntimeSec + $HoldOpenSec + 60
if ($ContinueToTrainPostprocess) {
    $pipelineRuntimeCapSec += $TrainPostprocessMaxRuntimeSec + $TrainPostprocessHoldOpenSec
}
$trainContinuationPhrase = if ($ContinueToTrainPostprocess) {
    ", затем visible train-only postprocess MaxRuntimeSec=$TrainPostprocessMaxRuntimeSec без automatic OOS, end-to-end runtime cap=$pipelineRuntimeCapSec sec"
} else {
    ""
}
$approvalPhrase = "Подтверждаю visible basis-v2 history collect plan_hash=$ExpectedPlanHash, run_id=$RunId, MaxRuntimeSec=$MaxRuntimeSec, collect hard deadline=$($window.not_later_than.ToString('o'))$trainContinuationPhrase, public API only, без grid/OOS/live/private API keys."
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -RunId $RunId -OutputRoot `"$OutputRoot`" -GatePath `"$GatePath`" -CurrentRunPath `"$CurrentRunPath`" -LaunchRecordPath `"$LaunchRecordPath`" -LogPath `"$LogPath`" -MaxRuntimeSec $MaxRuntimeSec -HoldOpenSec $HoldOpenSec -MinimumFreeGb $MinimumFreeGb -ApprovedNotBefore `"$($window.not_before.ToString('o'))`" -ApprovedNotLaterThan `"$($window.not_later_than.ToString('o'))`" -ConfirmedPublicHistoryCollect"
if ($Resume) { $approvalCommand += " -Resume" }
if ($ContinueToTrainPostprocess) {
    $approvalCommand += " -ContinueToTrainPostprocess -TrainPostprocessOutputRoot `"$TrainPostprocessOutputRoot`" -TrainPostprocessMaxRuntimeSec $TrainPostprocessMaxRuntimeSec -TrainPostprocessHoldOpenSec $TrainPostprocessHoldOpenSec"
}

if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_basis_v2_visible_collect_preview_v1"
        mode = "PlanOnly"
        decision = "AWAIT_EXPLICIT_BASIS_V2_HISTORY_COLLECT_APPROVAL"
        plan_path = $PlanPath
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = [string]$validation.plan_file_sha256
        python_runtime = [string]$env:TRADING_MVP_PYTHON
        candidate_count = [int]$validation.candidate_count
        run_id = $RunId
        output_root = $OutputRoot
        run_directory = $RunDirectory
        manifest_path = $ManifestPath
        max_runtime_sec = $MaxRuntimeSec
        estimated_public_requests = [int]$validation.candidate_count * 18
        estimated_runtime_sec = [Math]::Min(750, $MaxRuntimeSec)
        estimated_end_to_end_runtime_cap_sec = $pipelineRuntimeCapSec
        approved_not_before = $window.not_before.ToString("o")
        approved_not_later_than = $window.not_later_than.ToString("o")
        free_gb = $freeGb
        minimum_free_gb = $MinimumFreeGb
        gate_status = $(if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status })
        visible_terminal_required = $true
        network_access = $false
        collector_started = $false
        auto_resume = $false
        continue_to_train_postprocess = [bool]$ContinueToTrainPostprocess
        train_postprocess_output_root = $TrainPostprocessOutputRoot
        train_postprocess_max_runtime_sec = $TrainPostprocessMaxRuntimeSec
        train_postprocess_visible_terminal_required = [bool]$ContinueToTrainPostprocess
        train_postprocess_network_access = $false
        automatic_oos = $false
        grid_search = $false
        oos_read = $false
        live_orders = $false
        private_api_keys = $false
        approval_phrase = $approvalPhrase
        approval_command = $approvalCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}

if (-not $ConfirmedPublicHistoryCollect) {
    throw "ConfirmedPublicHistoryCollect is required for an actual collect. Run -PlanOnly first."
}
$now = [DateTimeOffset]::Now
if ($now -lt $window.not_before -or $now -ge $window.not_later_than) {
    throw "Current time is outside the explicitly approved collection window."
}
$runtimeDeadline = $now.AddSeconds($MaxRuntimeSec)
$deadline = if ($window.not_later_than -lt $runtimeDeadline) { $window.not_later_than } else { $runtimeDeadline }
$pipelineDeadline = $deadline.AddSeconds($HoldOpenSec + 60)
if ($ContinueToTrainPostprocess) {
    $pipelineDeadline = $pipelineDeadline.AddSeconds($TrainPostprocessMaxRuntimeSec + $TrainPostprocessHoldOpenSec)
}
if ($freeGb -lt $MinimumFreeGb) {
    throw "Disk guard failed: free_gb=$freeGb minimum_free_gb=$MinimumFreeGb output=$OutputRoot"
}
Assert-NoWriterLease
Assert-NoPitScheduleOverlap -Deadline $pipelineDeadline

if ($Resume) {
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Resume requires the original manifest: $ManifestPath"
    }
    $prior = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ($prior.final -eq $true) { throw "Cannot resume a final collector run." }
    if ([string]$prior.plan_hash -ne $ExpectedPlanHash) { throw "Resume plan hash mismatch." }
} elseif (Test-Path -LiteralPath $RunDirectory) {
    throw "Refusing to overwrite existing run directory: $RunDirectory"
}
if (Test-Path -LiteralPath $LaunchRecordPath) {
    throw "Refusing to overwrite immutable visible launch record: $LaunchRecordPath"
}

$token = [Guid]::NewGuid().ToString("N")
$launchRecord = [ordered]@{
    schema = "trading_mvp_basis_v2_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    created_at = $now.ToString("o")
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    python_runtime = [string]$env:TRADING_MVP_PYTHON
    output_root = $OutputRoot
    run_directory = $RunDirectory
    manifest_path = $ManifestPath
    log_path = $LogPath
    cwd = $ProjectRoot
    max_runtime_sec = $MaxRuntimeSec
    approved_not_before = $window.not_before.ToString("o")
    approved_not_later_than = $deadline.ToString("o")
    pipeline_hard_deadline = $pipelineDeadline.ToString("o")
    estimated_end_to_end_runtime_cap_sec = $pipelineRuntimeCapSec
    minimum_free_gb = $MinimumFreeGb
    free_gb_at_launch = $freeGb
    expected_public_requests = [int]$validation.candidate_count * 18
    visible_terminal = $true
    auto_resume = $false
    resume = [bool]$Resume
    continue_to_train_postprocess = [bool]$ContinueToTrainPostprocess
    train_postprocess_output_root = $TrainPostprocessOutputRoot
    train_postprocess_max_runtime_sec = $TrainPostprocessMaxRuntimeSec
    train_postprocess_visible_terminal = [bool]$ContinueToTrainPostprocess
    train_postprocess_network_access = $false
    automatic_oos = $false
    worker_token_sha256 = Get-TextSha256 -Value $token
    command = $approvalCommand
    research_only = $true
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$workerArguments = @(
    "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$PSCommandPath`"",
    "-Worker", "-WorkerToken", "`"$token`"",
    "-PlanPath", "`"$PlanPath`"",
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-RunId", $RunId,
    "-OutputRoot", "`"$OutputRoot`"",
    "-GatePath", "`"$GatePath`"",
    "-CurrentRunPath", "`"$CurrentRunPath`"",
    "-LaunchRecordPath", "`"$LaunchRecordPath`"",
    "-LogPath", "`"$LogPath`"",
    "-MaxRuntimeSec", "$MaxRuntimeSec",
    "-HoldOpenSec", "$HoldOpenSec",
    "-MinimumFreeGb", "$MinimumFreeGb",
    "-ApprovedNotBefore", "`"$($window.not_before.ToString('o'))`"",
    "-ApprovedNotLaterThan", "`"$($deadline.ToString('o'))`""
)
if ($Resume) { $workerArguments += "-Resume" }
$process = Start-Process -FilePath $pwsh -ArgumentList $workerArguments -WindowStyle Normal -PassThru
Update-LaunchRecord -Values @{
    status = "RUNNING"
    worker_pid = $process.Id
    started_at = ([DateTimeOffset]::Now.ToString("o"))
}
Write-Host "Visible basis-v2 history collect opened. PID=$($process.Id)" -ForegroundColor Green
Write-Host "Hard deadline: $($deadline.ToString('o'))"
Write-Host "Manifest: $ManifestPath"
Write-Host "Log: $LogPath"

$waitMs = [int][Math]::Ceiling(($deadline - [DateTimeOffset]::Now).TotalMilliseconds) + (($HoldOpenSec + 30) * 1000)
if ($waitMs -lt 1000 -or -not $process.WaitForExit($waitMs)) {
    try { $process.Kill($true) } catch { }
    try { $process.WaitForExit(5000) } catch { }
    $message = "Visible basis-v2 worker exceeded its hard deadline."
    Set-OwnedGateFailure -Reason "basis_v2_visible_deadline_exceeded" -Failure $message
    Update-LaunchRecord -Values @{
        status = "STOPPED_INCOMPLETE"
        completed_at = ([DateTimeOffset]::Now.ToString("o"))
        failure = $message
        worker_exit_code = -1
    }
    throw $message
}
if ($process.ExitCode -ne 0) {
    $message = "Visible basis-v2 worker exited with code $($process.ExitCode)."
    $gateAfter = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
    if ([string]$gateAfter.run_id -ne $RunId -or [string]$gateAfter.status -ne "STOPPED_INCOMPLETE") {
        Set-OwnedGateFailure -Reason "basis_v2_visible_worker_nonzero" -Failure $message
    }
    throw $message
}

if ($ContinueToTrainPostprocess) {
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Collector completed without its final manifest: $ManifestPath"
    }
    $collectorManifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if (
        $collectorManifest.final -ne $true -or
        [string]$collectorManifest.status -ne "READY_FOR_POSTPROCESS" -or
        [string]$collectorManifest.plan_hash -ne $ExpectedPlanHash -or
        [string]$collectorManifest.run_id -ne $RunId
    ) {
        throw "Collector manifest does not satisfy the sealed train-continuation contract."
    }

    $trainLaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.train-postprocess.visible-launch.json"
    $trainLogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.train-postprocess.visible.log"
    Update-LaunchRecord -Values @{
        status = "COLLECT_COMPLETED_TRAIN_POSTPROCESS_LAUNCHING"
        collector_completed_at = ([DateTimeOffset]::Now.ToString("o"))
        train_postprocess_launch_record_path = $trainLaunchRecordPath
        train_postprocess_log_path = $trainLogPath
    }
    Write-Host "Collector complete; opening sealed visible train-only postprocess." -ForegroundColor Cyan
    try {
        $trainArguments = @(
            "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $TrainPostprocessWrapper,
            "-PlanPath", $PlanPath,
            "-ExpectedPlanHash", $ExpectedPlanHash,
            "-CollectorManifestPath", $ManifestPath,
            "-OutputRoot", $TrainPostprocessOutputRoot,
            "-GatePath", $GatePath,
            "-LaunchRecordPath", $trainLaunchRecordPath,
            "-LogPath", $trainLogPath,
            "-MaxRuntimeSec", "$TrainPostprocessMaxRuntimeSec",
            "-HoldOpenSec", "$TrainPostprocessHoldOpenSec"
        )
        & $pwsh @trainArguments
        $trainExitCode = $LASTEXITCODE
        if ($trainExitCode -ne 0) {
            throw "Visible train-only postprocess exited with code $trainExitCode."
        }
        if (-not (Test-Path -LiteralPath $trainLaunchRecordPath)) {
            throw "Train postprocess exited without its launch record: $trainLaunchRecordPath"
        }
        $trainLaunch = Get-Content -LiteralPath $trainLaunchRecordPath -Raw | ConvertFrom-Json
        if ([string]$trainLaunch.status -ne "COMPLETED" -or -not $trainLaunch.result_manifest_path) {
            throw "Train postprocess launch record is not complete."
        }
        $trainResultPath = [System.IO.Path]::GetFullPath([string]$trainLaunch.result_manifest_path)
        if (-not (Test-Path -LiteralPath $trainResultPath)) {
            throw "Train postprocess result manifest is missing: $trainResultPath"
        }
        $trainResult = Get-Content -LiteralPath $trainResultPath -Raw | ConvertFrom-Json
        if (
            $trainResult.final -ne $true -or
            $trainResult.oos_read -ne $false -or
            [string]$trainResult.plan_hash -ne $ExpectedPlanHash -or
            [string]$trainResult.collector_run_id -ne $RunId
        ) {
            throw "Train postprocess result violates the sealed train-only contract."
        }
        Update-LaunchRecord -Values @{
            status = "COMPLETED_WITH_TRAIN_POSTPROCESS"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            train_postprocess_exit_code = 0
            train_postprocess_result_manifest_path = $trainResultPath
            train_postprocess_status = [string]$trainResult.status
            train_postprocess_verdict = [string]$trainResult.verdict
            train_postprocess_deterministic_result_hash = [string]$trainResult.deterministic_result_hash
            automatic_oos = $false
        }
        Write-Host "Sealed train-only postprocess complete; automatic OOS remains blocked." -ForegroundColor Green
    } catch {
        $trainFailure = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        Update-LaunchRecord -Values @{
            status = "COLLECT_COMPLETED_TRAIN_POSTPROCESS_STOPPED_INCOMPLETE"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            train_postprocess_failure = $trainFailure
            train_postprocess_exit_code = $(if ($null -ne $trainExitCode) { $trainExitCode } else { -1 })
            automatic_oos = $false
        }
        throw "Collector completed, but sealed train-only postprocess failed: $trainFailure"
    }
}

Get-Content -LiteralPath $LaunchRecordPath -Raw
