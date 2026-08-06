[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [string]$RunId = "",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1, 7200)][int]$MaxRuntimeSec = 7200,
    [ValidateRange(1, 8)][int]$Workers = 4,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [ValidateRange(1, 100000)][double]$MinimumFreeGb = 10,
    [switch]$ConfirmedPublicHistoryCollect,
    [switch]$Resume,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PlanModule = Join-Path $ProjectRoot "trading_mvp\src\gate_historical_membership_history_plan.py"
$CollectorModule = Join-Path $ProjectRoot "trading_mvp\src\gate_historical_membership_history_collector.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $CurrentRunPath) { $CurrentRunPath = Join-Path (Split-Path -Parent $GatePath) "current-run.json" }

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) { return [System.IO.Path]::GetFullPath($candidate) }
    }
    throw "Python runtime with requests is required. Set TRADING_MVP_PYTHON."
}

function Write-JsonAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Set-ObjectProperty {
    param([Parameter(Mandatory = $true)]$Object, [Parameter(Mandatory = $true)][string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-GateState {
    $json = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json
    if ($LASTEXITCODE -ne 0) { throw "Active run gate check failed with exit code $LASTEXITCODE." }
    return ((@($json) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Assert-GateStartAllowed {
    param([Parameter(Mandatory = $true)]$Gate)
    $status = if ($Gate.gate_status) { [string]$Gate.gate_status } else { [string]$Gate.status }
    if ($status -eq "RUNNING") { throw "History collect blocked by active run_id=$($Gate.run_id)." }
    if ($status -eq "STOPPED_INCOMPLETE" -and -not $Resume) {
        throw "Resolve or visibly resume STOPPED_INCOMPLETE before a new history collect."
    }
}

function Get-FreeGb {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $drive = Get-PSDrive -Name $root.TrimEnd('\').TrimEnd(':') -ErrorAction Stop
    return [Math]::Round($drive.Free / 1GB, 3)
}

function Assert-NoProtectedScheduleOverlap {
    param([Parameter(Mandatory = $true)]$Gate)
    $schedule = $Gate.approved_night_schedule
    if (-not $schedule -or [string]$schedule.status -ne "ACTIVE") { return }
    $schedulePath = [string]$schedule.plan_path
    if (-not $schedulePath -or -not (Test-Path -LiteralPath $schedulePath -PathType Leaf)) { return }
    $schedulePlan = Get-Content -LiteralPath $schedulePath -Raw | ConvertFrom-Json
    $now = [DateTimeOffset]::Now
    $finish = $now.AddSeconds($MaxRuntimeSec + $HoldOpenSec + 300)
    foreach ($segment in @($schedulePlan.segments)) {
        $rawStart = if ($segment.start_local) { [string]$segment.start_local } else { [string]$segment.start }
        if (-not $rawStart) { continue }
        try { $start = [DateTimeOffset]::Parse($rawStart, [Globalization.CultureInfo]::InvariantCulture) }
        catch { continue }
        if ($start -gt $now -and $finish -ge $start.AddMinutes(-5)) {
            throw "History collect would overlap protected PIT schedule at $($start.ToString('o'))."
        }
    }
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-ObjectProperty -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

function Set-RunState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$Final,
        [int]$WorkerPid = 0,
        [int]$CompletedTasks = 0,
        [int]$TotalTasks = 0,
        [int]$Errors = 0,
        [string]$StopReason = "",
        [string]$Failure = "",
        [string]$NextDecision = ""
    )
    if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
        $gate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
        $existingStatus = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
        if ($existingStatus -eq "RUNNING" -and [string]$gate.run_id -ne $RunId) {
            throw "Refusing to overwrite active gate owned by run_id=$($gate.run_id)."
        }
    } else {
        $gate = [pscustomobject]@{ schema = "active_run_gate_v2"; project = "trading_mvp" }
    }
    $processIds = if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { @($WorkerPid) } else { @() }
    foreach ($entry in @(
        @("run_id", $RunId), @("status", $Status), @("gate_status", $Status), @("final", $Final),
        @("updated_at", [DateTimeOffset]::Now.ToString("o")), @("stop_reason", $StopReason),
        @("failure", $Failure), @("manifest_path", $ManifestPath),
        @("output", [pscustomobject]@{ path = $OutputRoot; kind = "directory" }),
        @("completed_cycles", $CompletedTasks), @("total_cycles", $TotalTasks),
        @("remaining_cycles", [Math]::Max(0, $TotalTasks - $CompletedTasks)),
        @("rows", $CompletedTasks), @("errors", $Errors),
        @("primary_output_complete", $Final), @("expected_outputs_complete", $Final),
        @("collector_pid", $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })),
        @("monitor_pid", $null), @("process_ids", $processIds),
        @("replay_allowed", $false), @("grid_allowed", $false), @("backtest_allowed", $false),
        @("execution_probe_allowed", $false), @("paper_forward_allowed", $false),
        @("live_orders", $false), @("private_api_keys", $false), @("leverage_or_margin", $false),
        @("next_goal_decision", $NextDecision),
        @("next_step_after_ready", $(if ($Final) { "Run hash-bound membership-history quality only; do not evaluate returns yet." } else { "Status-only until the visible history collect finishes." }))
    )) { Set-ObjectProperty -Object $gate -Name $entry[0] -Value $entry[1] }
    Write-JsonAtomic -Path $GatePath -Value $gate
    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"; project = "trading_mvp"; run_id = $RunId; status = $Status
        updated_at = [DateTimeOffset]::Now.ToString("o"); manifest_path = $ManifestPath
        output = [ordered]@{ path = $OutputRoot; kind = "directory" }
        collector_pid = $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })
        monitor_pid = $null; process_ids = $processIds; launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

function Remove-OwnedWriterLock {
    if (-not (Test-Path -LiteralPath $WriterLockPath -PathType Leaf)) { return }
    try {
        $lock = Get-Content -LiteralPath $WriterLockPath -Raw | ConvertFrom-Json
        if ([string]$lock.run_id -eq $RunId) { Remove-Item -LiteralPath $WriterLockPath -Force }
    } catch { }
}

foreach ($path in @($PlanModule, $CollectorModule, $PlanPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
}
$PlanPath = (Resolve-Path -LiteralPath $PlanPath).Path
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$ManifestPath = [System.IO.Path]::GetFullPath($ManifestPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
$WriterLockPath = Join-Path $OutputRoot ".membership-history-writer.lock"
$python = Resolve-Python
$env:TRADING_MVP_PYTHON = $python
$validatorCode = @'
import importlib.util
import json
import pathlib
import sys

module_path, plan_path, expected = sys.argv[1:]
module_file = pathlib.Path(module_path).resolve()
sys.path.insert(0, str(module_file.parent))
spec = importlib.util.spec_from_file_location("gate_membership_history_plan_launch", module_file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.authorize_history_collect(plan_path, expected), ensure_ascii=False))
'@
$validationRaw = & $python -c $validatorCode $PlanModule $PlanPath $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Membership-history PlanOnly validation failed." }
$plan = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
if ([string]$plan.plan_hash -ne $ExpectedPlanHash) { throw "Validated history plan hash mismatch." }
if (-not $RunId) { $RunId = [string]$plan.run_id }
if ([string]$plan.run_id -ne $RunId) { throw "RunId does not match the frozen history plan." }
if (-not $LaunchRecordPath) {
    $suffix = if ($Resume) { ".resume.$(Get-Date -Format 'yyyyMMdd_HHmmss')" } else { "" }
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId$suffix.visible-launch.json"
}
if (-not $LogPath) {
    $suffix = if ($Resume) { ".resume.$(Get-Date -Format 'yyyyMMdd_HHmmss')" } else { "" }
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId$suffix.visible.log"
}
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) {
        throw "Worker token and launch record are required."
    }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) { throw "Worker token mismatch." }
    if ([string]$launch.run_id -ne $RunId -or [string]$launch.plan_hash -ne $ExpectedPlanHash) {
        throw "Worker launch identity mismatch."
    }
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate membership history - $RunId" } catch { }
    $env:PYTHONUNBUFFERED = "1"
    Update-LaunchRecord -Values @{ status = "RUNNING"; gate_status = "RUNNING"; worker_pid = $PID; collector_pid = $PID; process_ids = @($PID); worker_started_at = [DateTimeOffset]::Now.ToString("o") }
    Set-RunState -Status "RUNNING" -Final $false -WorkerPid $PID -TotalTasks @($plan.archive_tasks).Count -NextDecision "GATE_MEMBERSHIP_HISTORY_COLLECT_RUNNING"
    Write-Host "trading_mvp visible Gate membership-history archive collect" -ForegroundColor Cyan
    Write-Host "run_id=$RunId"
    Write-Host "plan_hash=$ExpectedPlanHash"
    Write-Host "tasks=$(@($plan.archive_tasks).Count) workers=$Workers"
    Write-Host "manifest=$ManifestPath"
    try {
        & $python $CollectorModule `
            --plan $PlanPath --expected-plan-hash $ExpectedPlanHash `
            --output-root $OutputRoot --manifest $ManifestPath `
            --max-runtime-sec $MaxRuntimeSec --max-workers $Workers 2>&1 |
            Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) { throw "membership-history collector exited with code $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Collector exited without manifest." }
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        if ($manifest.final -ne $true) { throw "Collector manifest is not final." }
        $completed = [int]$manifest.summary.completed_tasks
        $total = [int]$manifest.summary.total_tasks
        Update-LaunchRecord -Values @{ status = "READY_FOR_POSTPROCESS"; gate_status = "READY_FOR_POSTPROCESS"; final = $true; completed_at = [DateTimeOffset]::Now.ToString("o"); worker_exit_code = 0; collector_pid = $null; process_ids = @(); completed_cycles = $completed; total_cycles = $total; rows = $completed; artifact_hash = [string]$manifest.artifact_hash; decision = [string]$manifest.decision }
        Set-RunState -Status "READY_FOR_POSTPROCESS" -Final $true -CompletedTasks $completed -TotalTasks $total -NextDecision ([string]$manifest.decision)
        Write-Host "READY_FOR_POSTPROCESS completed=$completed/$total missing=$($manifest.summary.missing)" -ForegroundColor Green
        Remove-OwnedWriterLock
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        $completed = 0; $total = @($plan.archive_tasks).Count
        if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
            try { $partial = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json; $completed = [int]$partial.summary.completed_tasks; $total = [int]$partial.summary.total_tasks } catch { }
        }
        Update-LaunchRecord -Values @{ status = "STOPPED_INCOMPLETE"; gate_status = "STOPPED_INCOMPLETE"; final = $false; completed_at = [DateTimeOffset]::Now.ToString("o"); worker_exit_code = 1; collector_pid = $null; process_ids = @(); completed_cycles = $completed; total_cycles = $total; errors = 1; failure = $message }
        try { Set-RunState -Status "STOPPED_INCOMPLETE" -Final $false -CompletedTasks $completed -TotalTasks $total -Errors 1 -StopReason "gate_membership_history_collect_failed" -Failure $message -NextDecision "VISIBLE_RESUME_SAME_HISTORY_RUN_ID_REQUIRED" } catch { }
        Remove-OwnedWriterLock
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        Write-Host "Resume visibly with the same run_id and plan_hash." -ForegroundColor Yellow
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Get-GateState
Assert-GateStartAllowed -Gate $gate
Assert-NoProtectedScheduleOverlap -Gate $gate
$freeGb = Get-FreeGb -Path $OutputRoot
$approvalPhrase = [string]$plan.approval_phrase
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -OutputRoot `"$OutputRoot`" -ManifestPath `"$ManifestPath`" -RunId $RunId -MaxRuntimeSec $MaxRuntimeSec -Workers $Workers -ConfirmedPublicHistoryCollect"
if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_membership_history_visible_collect_preview_v1"
        mode = "PlanOnly"; decision = "AWAIT_EXPLICIT_HASH_BOUND_HISTORY_COLLECT_APPROVAL"
        plan_path = $PlanPath; plan_hash = $ExpectedPlanHash; run_id = $RunId
        output_root = $OutputRoot; manifest_path = $ManifestPath; launch_record_path = $LaunchRecordPath; log_path = $LogPath
        expected_tasks = @($plan.archive_tasks).Count; max_runtime_sec = $MaxRuntimeSec; workers = $Workers
        free_gb = $freeGb; minimum_free_gb = $MinimumFreeGb; visible_terminal_required = $true
        network_access = $false; collect_started = $false; resume = [bool]$Resume; auto_resume = $false
        returns_read = $false; oos_read = $false; grid_search = $false; live_orders = $false; private_api_keys = $false
        approval_phrase = $approvalPhrase; approval_command = $approvalCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}
if (-not $ConfirmedPublicHistoryCollect) { throw "ConfirmedPublicHistoryCollect is required. Run -PlanOnly first." }
if ($freeGb -lt $MinimumFreeGb) { throw "Disk guard failed: free_gb=$freeGb minimum_free_gb=$MinimumFreeGb" }
if ($Resume) {
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Resume manifest is missing: $ManifestPath" }
} elseif (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
    $existing = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ($existing.final -eq $true -and [string]$existing.plan_hash -eq $ExpectedPlanHash) {
        [ordered]@{ decision = "VALID_FINAL_HISTORY_CACHE_REUSED_NO_DUPLICATE_LAUNCH"; run_id = $RunId; plan_hash = $ExpectedPlanHash; manifest_path = $ManifestPath; artifact_hash = [string]$existing.artifact_hash; visible_terminal_started = $false } | ConvertTo-Json -Depth 8
        exit 0
    }
    throw "Existing non-final manifest requires -Resume with the same run_id."
}
if (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf) { throw "Refusing to overwrite immutable launch record: $LaunchRecordPath" }
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
if (Test-Path -LiteralPath $WriterLockPath -PathType Leaf) { throw "Membership-history writer lock already exists: $WriterLockPath" }
$token = [Guid]::NewGuid().ToString("N")
Write-JsonAtomic -Path $WriterLockPath -Value ([ordered]@{ run_id = $RunId; plan_hash = $ExpectedPlanHash; launcher_pid = $PID; created_at = [DateTimeOffset]::Now.ToString("o") })
$record = [ordered]@{
    schema = "trading_mvp_gate_membership_history_visible_launch_v1"; project = "trading_mvp"; run_id = $RunId
    status = "LAUNCHING"; gate_status = "LAUNCHING"; final = $false; created_at = [DateTimeOffset]::Now.ToString("o")
    plan_path = $PlanPath; plan_hash = $ExpectedPlanHash; output = [ordered]@{ path = $OutputRoot; kind = "directory" }
    manifest_path = $ManifestPath; log_path = $LogPath; max_runtime_sec = $MaxRuntimeSec; expected_duration_sec = $MaxRuntimeSec
    workers = $Workers; expected_tasks = @($plan.archive_tasks).Count; free_gb_at_launch = $freeGb; minimum_free_gb = $MinimumFreeGb
    worker_token_sha256 = Get-TextSha256 -Value $token; visible_terminal = $true; public_archive_only = $true
    resume = [bool]$Resume; auto_resume = $false; replay_allowed = $false; grid_allowed = $false; live_orders = $false; private_api_keys = $false
}
try {
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
    $script = @(
        "& $(Quote-PowerShellLiteral -Value $PSCommandPath)", "-PlanPath $(Quote-PowerShellLiteral -Value $PlanPath)",
        "-ExpectedPlanHash $(Quote-PowerShellLiteral -Value $ExpectedPlanHash)", "-OutputRoot $(Quote-PowerShellLiteral -Value $OutputRoot)",
        "-ManifestPath $(Quote-PowerShellLiteral -Value $ManifestPath)", "-RunId $(Quote-PowerShellLiteral -Value $RunId)",
        "-GatePath $(Quote-PowerShellLiteral -Value $GatePath)", "-CurrentRunPath $(Quote-PowerShellLiteral -Value $CurrentRunPath)",
        "-LaunchRecordPath $(Quote-PowerShellLiteral -Value $LaunchRecordPath)", "-LogPath $(Quote-PowerShellLiteral -Value $LogPath)",
        "-MaxRuntimeSec $MaxRuntimeSec", "-Workers $Workers", "-HoldOpenSec $HoldOpenSec", "-MinimumFreeGb $MinimumFreeGb",
        $(if ($Resume) { "-Resume" } else { "" }), "-Worker", "-WorkerToken $(Quote-PowerShellLiteral -Value $token)"
    ) | Where-Object { $_ }
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(($script -join " ")))
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $process = Start-Process -FilePath $pwsh -ArgumentList @("-NoLogo", "-NoProfile", "-EncodedCommand", $encoded) -WindowStyle Normal -PassThru
    Update-LaunchRecord -Values @{ status = "RUNNING"; gate_status = "RUNNING"; launcher_pid = $PID; worker_pid = $process.Id; collector_pid = $process.Id; process_ids = @($process.Id); started_at = [DateTimeOffset]::Now.ToString("o") }
    Set-RunState -Status "RUNNING" -Final $false -WorkerPid $process.Id -TotalTasks @($plan.archive_tasks).Count -NextDecision "GATE_MEMBERSHIP_HISTORY_COLLECT_RUNNING"
    [ordered]@{ decision = "VISIBLE_GATE_MEMBERSHIP_HISTORY_COLLECT_STARTED"; run_id = $RunId; plan_hash = $ExpectedPlanHash; worker_pid = $process.Id; manifest_path = $ManifestPath; launch_record_path = $LaunchRecordPath; log_path = $LogPath; expected_finish = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec).ToString("o"); visible_terminal = $true; auto_resume = $false } | ConvertTo-Json -Depth 8
} catch {
    Remove-OwnedWriterLock
    throw
}
