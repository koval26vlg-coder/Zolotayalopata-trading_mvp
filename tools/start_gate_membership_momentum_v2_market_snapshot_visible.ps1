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
    [ValidateRange(1, 4)][int]$Workers = 4,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$ConfirmedPublicMarketSnapshotCollect,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Module = Join-Path $ProjectRoot "trading_mvp\src\gate_membership_momentum_v2_market_snapshot.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $CurrentRunPath) { $CurrentRunPath = Join-Path (Split-Path -Parent $GatePath) "current-run.json" }

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
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
    if ($status -eq "RUNNING") { throw "Market snapshot blocked by active run_id=$($Gate.run_id)." }
    if ($status -eq "STOPPED_INCOMPLETE") { throw "Resolve STOPPED_INCOMPLETE before market snapshot collection." }
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) { Set-Property -Object $record -Name ([string]$entry.Key) -Value $entry.Value }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

function Set-RunState {
    param([Parameter(Mandatory = $true)][string]$Status, [Parameter(Mandatory = $true)][bool]$Final, [int]$WorkerPid = 0, [string]$Failure = "")
    $gate = if (Test-Path -LiteralPath $GatePath -PathType Leaf) { Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json } else { [pscustomobject]@{ schema = "active_run_gate_v2"; project = "trading_mvp" } }
    $processIds = if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { @($WorkerPid) } else { @() }
    foreach ($entry in @(
        @("run_id", $RunId), @("status", $Status), @("gate_status", $Status), @("final", $Final),
        @("updated_at", [DateTimeOffset]::Now.ToString("o")), @("manifest_path", $OutputPath),
        @("output", [pscustomobject]@{ path = $OutputPath; kind = "file" }), @("failure", $Failure),
        @("completed_cycles", $(if ($Final) { 1 } else { 0 })), @("total_cycles", 1), @("remaining_cycles", $(if ($Final) { 0 } else { 1 })),
        @("rows", $(if ($Final) { 1 } else { 0 })), @("errors", $(if ($Failure) { 1 } else { 0 })),
        @("collector_pid", $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })),
        @("monitor_pid", $null), @("process_ids", $processIds), @("replay_allowed", $false),
        @("grid_allowed", $false), @("paper_forward_allowed", $false), @("live_orders", $false),
        @("private_api_keys", $false), @("leverage_or_margin", $false),
        @("next_goal_decision", $(if ($Final) { "MARKET_SNAPSHOT_READY_FOR_CAUSAL_SELECTION" } elseif ($Status -eq "RUNNING") { "MARKET_SNAPSHOT_COLLECT_RUNNING" } else { "VISIBLE_RESTART_WITH_NEW_HASH_BOUND_WINDOW_REQUIRED" }))
    )) { Set-Property -Object $gate -Name $entry[0] -Value $entry[1] }
    Write-JsonAtomic -Path $GatePath -Value $gate
    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"; project = "trading_mvp"; run_id = $RunId; status = $Status
        updated_at = [DateTimeOffset]::Now.ToString("o"); manifest_path = $OutputPath
        output = [ordered]@{ path = $OutputPath; kind = "file" }; collector_pid = $(if ($WorkerPid -gt 0 -and $Status -eq "RUNNING") { $WorkerPid } else { $null })
        monitor_pid = $null; process_ids = $processIds; launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

foreach ($required in @($Module, $GateChecker, $PlanPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file is missing: $required" }
}
$PlanPath = (Resolve-Path -LiteralPath $PlanPath).Path
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
$python = Resolve-Python
$env:PYTHONPATH = (Join-Path $ProjectRoot "trading_mvp\src")
$validationRaw = & $python $Module validate --plan $PlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Market snapshot PlanOnly validation failed." }
$validation = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
if (-not $RunId) { $RunId = [string]$plan.run_id }
if ([string]$plan.run_id -ne $RunId -or [string]$validation.plan_hash -ne $ExpectedPlanHash) { throw "Market snapshot launch identity mismatch." }
if ($MaxRuntimeSec -gt [int]$plan.snapshot_contract.maximum_runtime_sec) { throw "MaxRuntimeSec exceeds frozen snapshot contract." }
if ($Workers -gt [int]$plan.snapshot_contract.maximum_workers) { throw "Workers exceeds frozen snapshot contract." }
if (-not $LaunchRecordPath) { $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.market-snapshot.visible-launch.json" }
if (-not $LogPath) { $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.market-snapshot.visible.log" }
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) { throw "Worker token/launch record missing." }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) { throw "Worker token mismatch." }
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate momentum-v2 market snapshot - $RunId" } catch { }
    Update-LaunchRecord -Values @{ status = "RUNNING"; gate_status = "RUNNING"; worker_pid = $PID; collector_pid = $PID; process_ids = @($PID); worker_started_at = [DateTimeOffset]::Now.ToString("o") }
    Set-RunState -Status "RUNNING" -Final $false -WorkerPid $PID
    Write-Host "Visible Gate momentum-v2 causal market snapshot" -ForegroundColor Cyan
    Write-Host "run_id=$RunId plan_hash=$ExpectedPlanHash"
    Write-Host "output=$OutputPath hard_deadline=$($plan.snapshot_contract.hard_deadline_ts)"
    try {
        & $python $Module collect --plan $PlanPath --expected-plan-hash $ExpectedPlanHash --output $OutputPath --max-runtime-sec $MaxRuntimeSec --workers $Workers 2>&1 | Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) { throw "market snapshot collector exited with code $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) { throw "Collector exited without snapshot artifact." }
        $artifact = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
        Update-LaunchRecord -Values @{ status = "READY_FOR_POSTPROCESS"; gate_status = "READY_FOR_POSTPROCESS"; final = $true; completed_at = [DateTimeOffset]::Now.ToString("o"); collector_pid = $null; process_ids = @(); artifact_hash = [string]$artifact.artifact_hash; decision = [string]$artifact.decision }
        Set-RunState -Status "READY_FOR_POSTPROCESS" -Final $true
        Write-Host "READY_FOR_POSTPROCESS artifact_hash=$($artifact.artifact_hash)" -ForegroundColor Green
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        Update-LaunchRecord -Values @{ status = "STOPPED_INCOMPLETE"; gate_status = "STOPPED_INCOMPLETE"; final = $false; completed_at = [DateTimeOffset]::Now.ToString("o"); collector_pid = $null; process_ids = @(); failure = $message }
        try { Set-RunState -Status "STOPPED_INCOMPLETE" -Final $false -Failure $message } catch { }
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Get-GateState
Assert-GateOpen -Gate $gate
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -OutputPath `"$OutputPath`" -RunId $RunId -MaxRuntimeSec $MaxRuntimeSec -Workers $Workers -ConfirmedPublicMarketSnapshotCollect"
if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_membership_momentum_v2_market_snapshot_visible_preview_v1"
        mode = "PlanOnly"; decision = "AWAIT_EXPLICIT_HASH_BOUND_MARKET_SNAPSHOT_APPROVAL"
        run_id = $RunId; plan_path = $PlanPath; plan_hash = $ExpectedPlanHash; output_path = $OutputPath
        not_before_ts = [int64]$plan.snapshot_contract.not_before_ts; hard_deadline_ts = [int64]$plan.snapshot_contract.hard_deadline_ts
        max_runtime_sec = $MaxRuntimeSec; workers = $Workers; visible_terminal_required = $true
        network_access = $false; collect_started = $false; oos_returns_read = $false; grid_search = $false
        live_orders = $false; private_api_keys = $false; approval_phrase = [string]$plan.approval_phrase
        approval_command = $approvalCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}
if (-not $ConfirmedPublicMarketSnapshotCollect) { throw "ConfirmedPublicMarketSnapshotCollect is required. Run -PlanOnly first." }
if (Test-Path -LiteralPath $OutputPath) { throw "Refusing to overwrite market snapshot output: $OutputPath" }
if (Test-Path -LiteralPath $LaunchRecordPath) { throw "Refusing to overwrite launch record: $LaunchRecordPath" }
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ($now -lt [int64]$plan.snapshot_contract.not_before_ts) { throw "Market snapshot is not due yet." }
if ($now -ge [int64]$plan.snapshot_contract.hard_deadline_ts) { throw "Market snapshot window missed; create a new globally anchored PlanOnly." }
$token = [Guid]::NewGuid().ToString("N")
$record = [ordered]@{
    schema = "trading_mvp_gate_membership_momentum_v2_market_snapshot_visible_launch_v1"; project = "trading_mvp"
    run_id = $RunId; status = "LAUNCHING"; gate_status = "LAUNCHING"; final = $false; created_at = [DateTimeOffset]::Now.ToString("o")
    plan_path = $PlanPath; plan_hash = $ExpectedPlanHash; output = [ordered]@{ path = $OutputPath; kind = "file" }
    manifest_path = $OutputPath; log_path = $LogPath; max_runtime_sec = $MaxRuntimeSec; workers = $Workers
    worker_token_sha256 = Get-TextSha256 -Value $token; visible_terminal = $true; public_api_only = $true
    auto_resume = $false; replay_allowed = $false; grid_allowed = $false; live_orders = $false; private_api_keys = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $record
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
$parts = @(
    "& $(Quote-Literal -Value $PSCommandPath)", "-PlanPath $(Quote-Literal -Value $PlanPath)",
    "-ExpectedPlanHash $(Quote-Literal -Value $ExpectedPlanHash)", "-OutputPath $(Quote-Literal -Value $OutputPath)",
    "-RunId $(Quote-Literal -Value $RunId)", "-GatePath $(Quote-Literal -Value $GatePath)",
    "-CurrentRunPath $(Quote-Literal -Value $CurrentRunPath)", "-LaunchRecordPath $(Quote-Literal -Value $LaunchRecordPath)",
    "-LogPath $(Quote-Literal -Value $LogPath)", "-MaxRuntimeSec $MaxRuntimeSec", "-Workers $Workers",
    "-HoldOpenSec $HoldOpenSec", "-Worker", "-WorkerToken $(Quote-Literal -Value $token)"
)
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(($parts -join " ")))
$process = Start-Process -FilePath (Get-Command pwsh -ErrorAction Stop).Source -ArgumentList @("-NoLogo", "-NoProfile", "-EncodedCommand", $encoded) -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
Update-LaunchRecord -Values @{ status = "RUNNING"; gate_status = "RUNNING"; launcher_pid = $PID; worker_pid = $process.Id; collector_pid = $process.Id; process_ids = @($process.Id); started_at = [DateTimeOffset]::Now.ToString("o") }
Set-RunState -Status "RUNNING" -Final $false -WorkerPid $process.Id
[ordered]@{
    decision = "VISIBLE_GATE_MOMENTUM_V2_MARKET_SNAPSHOT_STARTED"; run_id = $RunId; plan_hash = $ExpectedPlanHash
    worker_pid = $process.Id; output_path = $OutputPath; launch_record_path = $LaunchRecordPath; log_path = $LogPath
    expected_finish = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec).ToString("o"); visible_terminal = $true; auto_resume = $false
} | ConvertTo-Json -Depth 8
