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
    [ValidateRange(1, 8)][int]$Workers = 8,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60,
    [switch]$ConfirmedPublicProbe,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProbeModule = Join-Path $ProjectRoot "trading_mvp\src\gate_historical_membership_v3.py"
$WorkerScript = Join-Path $ProjectRoot "tools\run_gate_historical_membership_v3_probe_visible.ps1"
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

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-ObjectProperty -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-GateState {
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $json = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json
    if ($LASTEXITCODE -ne 0) { throw "Active run gate check failed with exit code $LASTEXITCODE." }
    return ((@($json) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Assert-GateOpen {
    param([Parameter(Mandatory = $true)]$Gate)
    $status = if ($Gate.gate_status) { [string]$Gate.gate_status } else { [string]$Gate.status }
    if ($status -eq "RUNNING") { throw "Public probe blocked by active gate status=RUNNING, run_id=$($Gate.run_id)." }
    if ($status -eq "STOPPED_INCOMPLETE") { throw "Resolve STOPPED_INCOMPLETE before starting the public probe." }
}

foreach ($required in @($ProbeModule, $WorkerScript, $GateChecker, $PlanPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file is missing: $required" }
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
spec = importlib.util.spec_from_file_location("gate_historical_membership_v3_launch", module_file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.authorize_probe(plan_path, expected), ensure_ascii=False))
'@
$validationRaw = & $python -c $validatorCode $ProbeModule $PlanPath $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Membership-v3 PlanOnly validation failed." }
$plan = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
if ([string]$plan.plan_hash -ne $ExpectedPlanHash) { throw "Validated plan hash does not match ExpectedPlanHash." }
if (-not $RunId) { $RunId = [string]$plan.run_id }
if ([string]$plan.run_id -ne $RunId) { throw "RunId does not match the frozen PlanOnly." }
if ($MaxRuntimeSec -gt [int]$plan.runtime_contract.max_runtime_sec) {
    throw "MaxRuntimeSec exceeds the frozen PlanOnly runtime contract."
}
if ($Workers -gt [int]$plan.runtime_contract.workers) {
    throw "Workers exceeds the frozen PlanOnly concurrency contract."
}
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.membership-v3.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.membership-v3.visible.log"
}
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$gate = Get-GateState
Assert-GateOpen -Gate $gate

$approvalPhrase = [string]$plan.approval_phrase
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -OutputPath `"$OutputPath`" -RunId $RunId -MaxRuntimeSec $MaxRuntimeSec -Workers $Workers -HoldOpenSec $HoldOpenSec -ConfirmedPublicProbe"
if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_historical_membership_v3_visible_probe_preview_v1"
        mode = "PlanOnly"
        decision = "AWAIT_EXPLICIT_HASH_BOUND_PUBLIC_PROBE_APPROVAL"
        plan_path = $PlanPath
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()
        module_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProbeModule).Hash.ToLowerInvariant()
        worker_script_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $WorkerScript).Hash.ToLowerInvariant()
        run_id = $RunId
        output_path = $OutputPath
        launch_record_path = $LaunchRecordPath
        log_path = $LogPath
        max_runtime_sec = $MaxRuntimeSec
        workers = $Workers
        gate_status = $(if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status })
        visible_terminal_required = $true
        network_access = $false
        archive_payload_read = $false
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

$createdAt = [DateTimeOffset]::Now
$launchRecord = [ordered]@{
    schema = "trading_mvp_gate_historical_membership_v3_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    gate_status = "LAUNCHING"
    final = $false
    created_at = $createdAt.ToString("o")
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()
    module_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProbeModule).Hash.ToLowerInvariant()
    worker_script_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $WorkerScript).Hash.ToLowerInvariant()
    output = [ordered]@{ path = $OutputPath; kind = "file" }
    manifest_path = $OutputPath
    log_path = $LogPath
    gate_path = $GatePath
    current_run_path = $CurrentRunPath
    max_runtime_sec = $MaxRuntimeSec
    expected_duration_sec = $MaxRuntimeSec
    workers = $Workers
    visible_terminal = $true
    public_archive_metadata_only = $true
    archive_payload_read = $false
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
    "& $(Quote-PowerShellLiteral -Value $WorkerScript)",
    "-PlanPath $(Quote-PowerShellLiteral -Value $PlanPath)",
    "-ExpectedPlanHash $(Quote-PowerShellLiteral -Value $ExpectedPlanHash)",
    "-OutputPath $(Quote-PowerShellLiteral -Value $OutputPath)",
    "-RunId $(Quote-PowerShellLiteral -Value $RunId)",
    "-MaxRuntimeSec $MaxRuntimeSec",
    "-Workers $Workers",
    "-HoldOpenSec $HoldOpenSec",
    "-GatePath $(Quote-PowerShellLiteral -Value $GatePath)",
    "-CurrentRunPath $(Quote-PowerShellLiteral -Value $CurrentRunPath)",
    "-LaunchRecordPath $(Quote-PowerShellLiteral -Value $LaunchRecordPath)",
    "-LogPath $(Quote-PowerShellLiteral -Value $LogPath)"
) -join " "
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
try {
    $process = Start-Process -FilePath $pwsh -ArgumentList @("-NoLogo", "-NoProfile", "-EncodedCommand", $encoded) `
        -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
    Update-LaunchRecord -Values @{
        status = "STARTED"
        gate_status = "STARTING"
        launcher_pid = $PID
        worker_pid = $process.Id
        collector_pid = $process.Id
        process_ids = @($process.Id)
        started_at = [DateTimeOffset]::Now.ToString("o")
    }
} catch {
    Update-LaunchRecord -Values @{
        status = "STOPPED_INCOMPLETE"
        gate_status = "STOPPED_INCOMPLETE"
        final = $false
        failure = $_.Exception.Message
        completed_at = [DateTimeOffset]::Now.ToString("o")
    }
    throw
}

[ordered]@{
    decision = "VISIBLE_GATE_HISTORICAL_MEMBERSHIP_V3_PROBE_STARTED"
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
