[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$RunId = "",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1, 600)][int]$MaxRuntimeSec = 600,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$ConfirmedPublicProbe,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProbeModule = Join-Path $ProjectRoot "trading_mvp\src\gate_historical_membership_v2.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path (Split-Path -Parent $GatePath) "current-run.json"
}

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
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime with requests is required. Set TRADING_MVP_PYTHON."
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
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

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-GateState {
    $json = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Active run gate check failed with exit code $LASTEXITCODE."
    }
    return ((@($json) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Assert-GateOpen {
    param([Parameter(Mandatory = $true)]$Gate)
    $status = if ($Gate.gate_status) { [string]$Gate.gate_status } else { [string]$Gate.status }
    if ($status -eq "RUNNING") {
        throw "Public probe blocked by active gate status=RUNNING, run_id=$($Gate.run_id)."
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before starting the public probe."
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
        [int]$Rows = 0,
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
        @("run_id", $RunId),
        @("status", $Status),
        @("gate_status", $Status),
        @("final", $Final),
        @("updated_at", [DateTimeOffset]::Now.ToString("o")),
        @("stop_reason", $StopReason),
        @("failure", $Failure),
        @("manifest_path", $OutputPath),
        @("output", [pscustomobject]@{ path = $OutputPath; kind = "file" }),
        @("completed_cycles", $(if ($Final) { 1 } else { 0 })),
        @("total_cycles", 1),
        @("remaining_cycles", $(if ($Final) { 0 } else { 1 })),
        @("rows", $Rows),
        @("errors", $Errors),
        @("primary_output_complete", $Final),
        @("expected_outputs_complete", $Final),
        @("collector_pid", $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })),
        @("monitor_pid", $null),
        @("process_ids", $processIds),
        @("replay_allowed", $false),
        @("grid_allowed", $false),
        @("backtest_allowed", $false),
        @("execution_probe_allowed", $false),
        @("paper_forward_allowed", $false),
        @("live_orders", $false),
        @("private_api_keys", $false),
        @("leverage_or_margin", $false),
        @("next_goal_decision", $NextDecision),
        @("next_goal_reason", $(
            if (-not $Final) {
                "Membership-v2 public probe is still running or stopped incomplete."
            } elseif ($NextDecision -eq "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY") {
                "Frozen membership-v2 technical source gates passed; only a separate hash-bound history PlanOnly may follow."
            } else {
                "Frozen membership-v2 technical source gates failed; history, train, OOS and retune remain forbidden."
            }
        )),
        @("next_step_after_ready", $(if ($Final) { "Read only the membership-v2 technical verdict; build a separate hash-bound history PlanOnly only if accepted." } else { "Status-only until this public probe finishes." }))
    )) {
        Set-ObjectProperty -Object $gate -Name $entry[0] -Value $entry[1]
    }
    Write-JsonAtomic -Path $GatePath -Value $gate

    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = $RunId
        status = $Status
        updated_at = [DateTimeOffset]::Now.ToString("o")
        manifest_path = $OutputPath
        output = [ordered]@{ path = $OutputPath; kind = "file" }
        collector_pid = $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })
        monitor_pid = $null
        process_ids = $processIds
        launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

if (-not (Test-Path -LiteralPath $ProbeModule -PathType Leaf)) {
    throw "Membership-v2 module is missing: $ProbeModule"
}
if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "Membership-v2 PlanOnly is missing: $PlanPath"
}
$PlanPath = (Resolve-Path -LiteralPath $PlanPath).Path
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
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
spec = importlib.util.spec_from_file_location("gate_historical_membership_v2_launch", module_file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.authorize_probe(plan_path, expected), ensure_ascii=False))
'@
$validationRaw = & $python -c $validatorCode $ProbeModule $PlanPath $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Membership-v2 PlanOnly validation failed." }
$plan = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
if ([string]$plan.plan_hash -ne $ExpectedPlanHash) {
    throw "Validated plan hash does not match ExpectedPlanHash."
}
if (-not $RunId) { $RunId = [string]$plan.run_id }
if ([string]$plan.run_id -ne $RunId) { throw "RunId does not match the frozen PlanOnly." }
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.visible.log"
}
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) {
        throw "Worker token and launch record are required."
    }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) {
        throw "Worker token mismatch."
    }
    if ([string]$launch.run_id -ne $RunId -or [string]$launch.plan_hash -ne $ExpectedPlanHash) {
        throw "Worker launch identity mismatch."
    }
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate membership-v2 probe - $RunId" } catch { }
    $env:PYTHONUNBUFFERED = "1"
    Update-LaunchRecord -Values @{
        status = "RUNNING"
        gate_status = "RUNNING"
        worker_pid = $PID
        collector_pid = $PID
        process_ids = @($PID)
        worker_started_at = [DateTimeOffset]::Now.ToString("o")
    }
    Set-RunState -Status "RUNNING" -Final $false -WorkerPid $PID -NextDecision "MEMBERSHIP_V2_PUBLIC_PROBE_RUNNING"
    Write-Host "trading_mvp visible Gate historical-membership v2 public probe" -ForegroundColor Cyan
    Write-Host "run_id=$RunId"
    Write-Host "plan_hash=$ExpectedPlanHash"
    Write-Host "output=$OutputPath"
    Write-Host "max_runtime_sec=$MaxRuntimeSec"
    try {
        & $python $ProbeModule probe `
            --plan $PlanPath `
            --expected-plan-hash $ExpectedPlanHash `
            --output $OutputPath `
            --max-runtime-sec $MaxRuntimeSec 2>&1 |
            Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) { throw "membership-v2 probe exited with code $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
            throw "Membership-v2 probe exited without output: $OutputPath"
        }
        $report = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
        if ($report.final -ne $true) {
            $detail = @($report.errors) -join "; "
            throw "Membership-v2 probe is incomplete: $detail"
        }
        if ([string]$report.plan_hash -ne $ExpectedPlanHash) {
            throw "Membership-v2 output plan hash mismatch."
        }
        $rowCount = @($report.rows).Count
        Update-LaunchRecord -Values @{
            status = "READY_FOR_POSTPROCESS"
            gate_status = "READY_FOR_POSTPROCESS"
            final = $true
            completed_at = [DateTimeOffset]::Now.ToString("o")
            worker_exit_code = 0
            collector_pid = $null
            process_ids = @()
            rows = $rowCount
            artifact_hash = [string]$report.artifact_hash
            decision = [string]$report.decision
        }
        Set-RunState -Status "READY_FOR_POSTPROCESS" -Final $true -Rows $rowCount -NextDecision ([string]$report.decision)
        Write-Host "READY_FOR_POSTPROCESS decision=$($report.decision) rows=$rowCount" -ForegroundColor Green
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        Update-LaunchRecord -Values @{
            status = "STOPPED_INCOMPLETE"
            gate_status = "STOPPED_INCOMPLETE"
            final = $false
            completed_at = [DateTimeOffset]::Now.ToString("o")
            worker_exit_code = 1
            collector_pid = $null
            process_ids = @()
            errors = 1
            failure = $message
        }
        try {
            Set-RunState -Status "STOPPED_INCOMPLETE" -Final $false -Errors 1 `
                -StopReason "gate_historical_membership_v2_probe_failed" -Failure $message `
                -NextDecision "RESUME_SAME_MEMBERSHIP_V2_PROBE_AFTER_CONFIRMING_NO_ACTIVE_WRITER"
        } catch { }
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Get-GateState
Assert-GateOpen -Gate $gate
$approvalPhrase = [string]$plan.approval_phrase
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -OutputPath `"$OutputPath`" -RunId $RunId -MaxRuntimeSec $MaxRuntimeSec -HoldOpenSec $HoldOpenSec -ConfirmedPublicProbe"

if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_historical_membership_v2_visible_probe_preview_v1"
        mode = "PlanOnly"
        decision = "AWAIT_EXPLICIT_HASH_BOUND_PUBLIC_PROBE_APPROVAL"
        plan_path = $PlanPath
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()
        module_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProbeModule).Hash.ToLowerInvariant()
        run_id = $RunId
        output_path = $OutputPath
        launch_record_path = $LaunchRecordPath
        log_path = $LogPath
        max_runtime_sec = $MaxRuntimeSec
        gate_status = $(if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status })
        visible_terminal_required = $true
        network_access = $false
        probe_started = $false
        auto_resume = $false
        returns_read = $false
        oos_read = $false
        grid_search = $false
        live_orders = $false
        private_api_keys = $false
        leverage_or_margin = $false
        approval_phrase = $approvalPhrase
        approval_command = $approvalCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}

if (-not $ConfirmedPublicProbe) {
    throw "ConfirmedPublicProbe is required for an actual public probe. Run -PlanOnly first."
}
if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
    $cached = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
    if ($cached.final -eq $true -and [string]$cached.plan_hash -eq $ExpectedPlanHash) {
        [ordered]@{
            decision = "VALID_FINAL_PROBE_CACHE_REUSED_NO_DUPLICATE_LAUNCH"
            run_id = $RunId
            plan_hash = $ExpectedPlanHash
            output_path = $OutputPath
            artifact_hash = [string]$cached.artifact_hash
            probe_decision = [string]$cached.decision
            visible_terminal_started = $false
        } | ConvertTo-Json -Depth 8
        exit 0
    }
    throw "Refusing to overwrite non-final or mismatched probe output: $OutputPath"
}
if (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf) {
    throw "Refusing to overwrite immutable visible launch record: $LaunchRecordPath"
}

$token = [Guid]::NewGuid().ToString("N")
$createdAt = [DateTimeOffset]::Now
$launchRecord = [ordered]@{
    schema = "trading_mvp_gate_historical_membership_v2_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    gate_status = "LAUNCHING"
    final = $false
    created_at = $createdAt.ToString("o")
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    output = [ordered]@{ path = $OutputPath; kind = "file" }
    manifest_path = $OutputPath
    log_path = $LogPath
    max_runtime_sec = $MaxRuntimeSec
    expected_duration_sec = $MaxRuntimeSec
    worker_token_sha256 = Get-TextSha256 -Value $token
    visible_terminal = $true
    public_api_only = $true
    auto_resume = $false
    replay_allowed = $false
    grid_allowed = $false
    execution_probe_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

$script = @(
    "& $(Quote-PowerShellLiteral -Value $PSCommandPath)",
    "-PlanPath $(Quote-PowerShellLiteral -Value $PlanPath)",
    "-ExpectedPlanHash $(Quote-PowerShellLiteral -Value $ExpectedPlanHash)",
    "-OutputPath $(Quote-PowerShellLiteral -Value $OutputPath)",
    "-RunId $(Quote-PowerShellLiteral -Value $RunId)",
    "-GatePath $(Quote-PowerShellLiteral -Value $GatePath)",
    "-CurrentRunPath $(Quote-PowerShellLiteral -Value $CurrentRunPath)",
    "-LaunchRecordPath $(Quote-PowerShellLiteral -Value $LaunchRecordPath)",
    "-LogPath $(Quote-PowerShellLiteral -Value $LogPath)",
    "-MaxRuntimeSec $MaxRuntimeSec",
    "-HoldOpenSec $HoldOpenSec",
    "-Worker",
    "-WorkerToken $(Quote-PowerShellLiteral -Value $token)"
) -join " "
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$process = Start-Process -FilePath $pwsh -ArgumentList @("-NoLogo", "-NoProfile", "-EncodedCommand", $encoded) -WindowStyle Normal -PassThru
Update-LaunchRecord -Values @{
    status = "RUNNING"
    gate_status = "RUNNING"
    launcher_pid = $PID
    worker_pid = $process.Id
    collector_pid = $process.Id
    process_ids = @($process.Id)
    started_at = [DateTimeOffset]::Now.ToString("o")
}
Set-RunState -Status "RUNNING" -Final $false -WorkerPid $process.Id -NextDecision "MEMBERSHIP_V2_PUBLIC_PROBE_RUNNING"
[ordered]@{
    decision = "VISIBLE_GATE_HISTORICAL_MEMBERSHIP_V2_PROBE_STARTED"
    run_id = $RunId
    plan_hash = $ExpectedPlanHash
    worker_pid = $process.Id
    output_path = $OutputPath
    launch_record_path = $LaunchRecordPath
    log_path = $LogPath
    expected_finish = $createdAt.AddSeconds($MaxRuntimeSec).ToString("o")
    visible_terminal = $true
    auto_resume = $false
} | ConvertTo-Json -Depth 8
