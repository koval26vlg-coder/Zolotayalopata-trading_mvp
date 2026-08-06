[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WindowPlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1200, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$ConfirmedPublicExecutionProbe,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Module = Join-Path $ProjectRoot "trading_mvp\src\gate_membership_momentum_v2_execution_probe_runtime.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $CurrentRunPath) { $CurrentRunPath = Join-Path (Split-Path -Parent $GatePath) "current-run.json" }

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python3.13t.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe"
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

function Set-Property {
    param([Parameter(Mandatory = $true)]$Object, [Parameter(Mandatory = $true)][string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Quote-Literal {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-GateState {
    $json = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json
    if ($LASTEXITCODE -ne 0) { throw "Active run gate check failed with exit code $LASTEXITCODE." }
    return ((@($json) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Assert-GateOpen {
    param([Parameter(Mandatory = $true)]$Gate)
    $status = if ($Gate.gate_status) { [string]$Gate.gate_status } else { [string]$Gate.status }
    if ($status -eq "RUNNING") { throw "Execution probe blocked by active run_id=$($Gate.run_id)." }
    if ($status -eq "STOPPED_INCOMPLETE") { throw "Resolve STOPPED_INCOMPLETE before execution-probe collection." }
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-Property -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

function Set-RunState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$Final,
        [int]$WorkerPid = 0,
        [string]$Failure = "",
        $Manifest = $null
    )
    $gate = if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
        Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
    } else {
        [pscustomobject]@{ schema = "active_run_gate_v2"; project = "trading_mvp" }
    }
    $processIds = if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { @($WorkerPid) } else { @() }
    $completedCycles = if ($Manifest) { [int]$Manifest.completed_cycles } elseif ($Final) { 240 } else { 0 }
    $totalCycles = if ($Manifest) { [int]$Manifest.expected_cycles } else { 240 }
    $rows = if ($Manifest -and $Manifest.samples) { [int]$Manifest.samples.rows } else { 0 }
    $errors = if ($Manifest) { [int]$Manifest.error_count + [int]$Manifest.critical_error_count } elseif ($Failure) { 1 } else { 0 }
    $nextDecision = if ($Status -eq "RUNNING") {
        "MEMBERSHIP_MOMENTUM_V2_EXECUTION_PROBE_RUNNING"
    } elseif ($Final) {
        "MEMBERSHIP_MOMENTUM_V2_EXECUTION_PROBE_WINDOW_READY"
    } else {
        "VISIBLE_NEW_HASH_BOUND_WINDOW_REQUIRED"
    }
    foreach ($entry in @(
        @("run_id", $RunId), @("status", $Status), @("gate_status", $Status), @("final", $Final),
        @("updated_at", [DateTimeOffset]::Now.ToString("o")), @("manifest_path", $ManifestPath),
        @("output", [pscustomobject]@{ path = $ManifestPath; kind = "file" }), @("failure", $Failure),
        @("completed_cycles", $completedCycles), @("total_cycles", $totalCycles),
        @("remaining_cycles", [Math]::Max(0, $totalCycles - $completedCycles)), @("rows", $rows), @("errors", $errors),
        @("collector_pid", $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })),
        @("monitor_pid", $null), @("process_ids", $processIds), @("replay_allowed", $false),
        @("grid_allowed", $false), @("paper_forward_allowed", $false), @("live_orders", $false),
        @("private_api_keys", $false), @("leverage_or_margin", $false), @("next_goal_decision", $nextDecision),
        @("next_step_after_ready", $(if ($Final) { "Collect the remaining frozen execution windows or run offline evaluation after all three are final." } else { "Create a new hash-bound PlanOnly for the missed or incomplete window; never resume partial samples." }))
    )) { Set-Property -Object $gate -Name $entry[0] -Value $entry[1] }
    Write-JsonAtomic -Path $GatePath -Value $gate
    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"; project = "trading_mvp"; run_id = $RunId; status = $Status
        updated_at = [DateTimeOffset]::Now.ToString("o"); manifest_path = $ManifestPath
        output = [ordered]@{ path = $ManifestPath; kind = "file" }
        collector_pid = $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })
        monitor_pid = $null; process_ids = $processIds; launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

foreach ($required in @($Module, $GateChecker, $WindowPlanPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file is missing: $required" }
}
$WindowPlanPath = (Resolve-Path -LiteralPath $WindowPlanPath).Path
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
$python = Resolve-Python
$env:PYTHONPATH = Join-Path $ProjectRoot "trading_mvp\src"
$env:PYTHONUNBUFFERED = "1"
$validationRaw = & $python $Module validate-plan --plan $WindowPlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Execution-probe window PlanOnly validation failed." }
$validation = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
$plan = Get-Content -LiteralPath $WindowPlanPath -Raw | ConvertFrom-Json
$RunId = [string]$plan.run_id
$SamplesPath = [System.IO.Path]::GetFullPath([string]$plan.output_contract.samples_path)
$ManifestPath = [System.IO.Path]::GetFullPath([string]$plan.output_contract.manifest_path)
if ([string]$validation.plan_hash -ne $ExpectedPlanHash) { throw "Execution-probe launch identity mismatch." }
if ($MaxRuntimeSec -gt [int]$plan.collector_contract.maximum_runtime_sec) { throw "MaxRuntimeSec exceeds frozen execution-probe contract." }
if (-not $LaunchRecordPath) { $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.execution-probe.visible-launch.json" }
if (-not $LogPath) { $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.execution-probe.visible.log" }
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) { throw "Worker token/launch record missing." }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) { throw "Worker token mismatch." }
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate momentum-v2 execution probe - $RunId" } catch { }
    Update-LaunchRecord -Values @{ status = "RUNNING"; gate_status = "RUNNING"; worker_pid = $PID; collector_pid = $PID; process_ids = @($PID); worker_started_at = [DateTimeOffset]::Now.ToString("o") }
    Set-RunState -Status "RUNNING" -Final $false -WorkerPid $PID
    Write-Host "Visible Gate membership-momentum-v2 execution probe" -ForegroundColor Cyan
    Write-Host "run_id=$RunId plan_hash=$ExpectedPlanHash window=$($plan.window_contract.index)"
    Write-Host "samples=$SamplesPath manifest=$ManifestPath"
    Write-Host "window_start=$($plan.window_contract.start_utc) window_end=$($plan.window_contract.end_utc)"
    try {
        & $python $Module collect --plan $WindowPlanPath --expected-plan-hash $ExpectedPlanHash --max-runtime-sec $MaxRuntimeSec 2>&1 | Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) { throw "execution-probe collector exited with code $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Collector exited without final manifest." }
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        if (-not [bool]$manifest.final -or [string]$manifest.status -ne "READY_FOR_POSTPROCESS") { throw "Execution-probe manifest is not final." }
        Update-LaunchRecord -Values @{ status = "READY_FOR_POSTPROCESS"; gate_status = "READY_FOR_POSTPROCESS"; final = $true; completed_at = [DateTimeOffset]::Now.ToString("o"); collector_pid = $null; process_ids = @(); deterministic_result_hash = [string]$manifest.deterministic_result_hash; completed_cycles = [int]$manifest.completed_cycles; rows = [int]$manifest.samples.rows }
        Set-RunState -Status "READY_FOR_POSTPROCESS" -Final $true -Manifest $manifest
        Write-Host "READY_FOR_POSTPROCESS cycles=$($manifest.completed_cycles)/$($manifest.expected_cycles) rows=$($manifest.samples.rows) eligible=$($manifest.metrics.eligible_asset_count)" -ForegroundColor Green
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        $partialManifest = if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) { Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json } else { $null }
        Update-LaunchRecord -Values @{ status = "STOPPED_INCOMPLETE"; gate_status = "STOPPED_INCOMPLETE"; final = $false; completed_at = [DateTimeOffset]::Now.ToString("o"); collector_pid = $null; process_ids = @(); failure = $message }
        try { Set-RunState -Status "STOPPED_INCOMPLETE" -Final $false -Failure $message -Manifest $partialManifest } catch { }
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Get-GateState
Assert-GateOpen -Gate $gate
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -WindowPlanPath `"$WindowPlanPath`" -ExpectedPlanHash $ExpectedPlanHash -MaxRuntimeSec $MaxRuntimeSec -ConfirmedPublicExecutionProbe"
if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_membership_momentum_v2_execution_probe_visible_preview_v1"
        mode = "PlanOnly"; decision = "AWAIT_EXPLICIT_HASH_BOUND_EXECUTION_PROBE_APPROVAL"
        run_id = $RunId; plan_path = $WindowPlanPath; plan_hash = $ExpectedPlanHash
        window_index = [int]$plan.window_contract.index; window_start_utc = [string]$plan.window_contract.start_utc
        window_end_utc = [string]$plan.window_contract.end_utc; samples_path = $SamplesPath; manifest_path = $ManifestPath
        max_runtime_sec = $MaxRuntimeSec; visible_terminal_required = $true; network_access = $false
        collect_started = $false; returns_read = $false; oos_read = $false; grid_search = $false
        live_orders = $false; private_api_keys = $false; approval_phrase = [string]$plan.approval_phrase
        approval_command = $approvalCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}
if (-not $ConfirmedPublicExecutionProbe) { throw "ConfirmedPublicExecutionProbe is required. Run -PlanOnly first." }
if (Test-Path -LiteralPath $SamplesPath) { throw "Refusing to overwrite execution-probe samples: $SamplesPath" }
if (Test-Path -LiteralPath $ManifestPath) { throw "Refusing to overwrite execution-probe manifest: $ManifestPath" }
if (Test-Path -LiteralPath $LaunchRecordPath) { throw "Refusing to overwrite launch record: $LaunchRecordPath" }
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$startTs = [int64]$plan.window_contract.start_ts
$endTs = [int64]$plan.window_contract.end_ts
if ($now -ge $endTs) { throw "Execution-probe window missed; create a new hash-bound window PlanOnly." }
if (($startTs - $now) + [int]$plan.window_contract.duration_sec -gt $MaxRuntimeSec) { throw "MaxRuntimeSec does not cover countdown plus frozen execution window." }
if ($now -gt $startTs + [int]$plan.window_contract.interval_sec) { throw "Execution-probe window start was missed." }
$token = [Guid]::NewGuid().ToString("N")
$record = [ordered]@{
    schema = "trading_mvp_gate_membership_momentum_v2_execution_probe_visible_launch_v1"; project = "trading_mvp"
    run_id = $RunId; status = "LAUNCHING"; gate_status = "LAUNCHING"; final = $false; created_at = [DateTimeOffset]::Now.ToString("o")
    plan_path = $WindowPlanPath; plan_hash = $ExpectedPlanHash; window_index = [int]$plan.window_contract.index
    output = [ordered]@{ path = $ManifestPath; kind = "file" }; manifest_path = $ManifestPath; samples_path = $SamplesPath
    log_path = $LogPath; max_runtime_sec = $MaxRuntimeSec; worker_token_sha256 = Get-TextSha256 -Value $token
    visible_terminal = $true; public_api_only = $true; auto_resume = $false; replay_allowed = $false
    grid_allowed = $false; live_orders = $false; private_api_keys = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $record
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
$parts = @(
    "& $(Quote-Literal -Value $PSCommandPath)", "-WindowPlanPath $(Quote-Literal -Value $WindowPlanPath)",
    "-ExpectedPlanHash $(Quote-Literal -Value $ExpectedPlanHash)", "-GatePath $(Quote-Literal -Value $GatePath)",
    "-CurrentRunPath $(Quote-Literal -Value $CurrentRunPath)", "-LaunchRecordPath $(Quote-Literal -Value $LaunchRecordPath)",
    "-LogPath $(Quote-Literal -Value $LogPath)", "-MaxRuntimeSec $MaxRuntimeSec", "-HoldOpenSec $HoldOpenSec",
    "-Worker", "-WorkerToken $(Quote-Literal -Value $token)"
)
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(($parts -join " ")))
$process = Start-Process -FilePath (Get-Command pwsh -ErrorAction Stop).Source -ArgumentList @("-NoLogo", "-NoProfile", "-EncodedCommand", $encoded) -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
Update-LaunchRecord -Values @{ status = "RUNNING"; gate_status = "RUNNING"; launcher_pid = $PID; worker_pid = $process.Id; collector_pid = $process.Id; process_ids = @($process.Id); started_at = [DateTimeOffset]::Now.ToString("o") }
Set-RunState -Status "RUNNING" -Final $false -WorkerPid $process.Id
[ordered]@{
    decision = "VISIBLE_GATE_MEMBERSHIP_MOMENTUM_V2_EXECUTION_PROBE_STARTED"; run_id = $RunId
    plan_hash = $ExpectedPlanHash; window_index = [int]$plan.window_contract.index; worker_pid = $process.Id
    samples_path = $SamplesPath; manifest_path = $ManifestPath; launch_record_path = $LaunchRecordPath; log_path = $LogPath
    expected_finish = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec).ToString("o"); visible_terminal = $true; auto_resume = $false
} | ConvertTo-Json -Depth 8
