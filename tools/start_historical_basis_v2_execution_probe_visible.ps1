[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [ValidateRange(0, 2)][int]$WindowIndex,
    [string]$RunId = "",
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\execution-probes",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1200, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$ConfirmedExecutionProbe,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
$LocalValidator = Join-Path $ProjectRoot "trading_mvp\src\historical_basis_v2_execution_probe.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path (Split-Path -Parent $GatePath) "current-run.json"
}
if (-not $RunId) {
    $prefixLength = [Math]::Min(12, $ExpectedPlanHash.Length)
    $RunId = "basis_v2_probe_$($ExpectedPlanHash.Substring(0, $prefixLength))_w$WindowIndex"
}
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.visible.log"
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    $resolved = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($resolved) { return [System.IO.Path]::GetFullPath($resolved) }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
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

function Resolve-Validator {
    param([Parameter(Mandatory = $true)]$Plan)
    $manifest = [string]$Plan.code_provenance.code_snapshot_manifest
    if ($manifest -and (Test-Path -LiteralPath $manifest)) {
        $candidate = Join-Path (Split-Path -Parent $manifest) "historical_basis_v2_execution_probe.py"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $LocalValidator
}

function Get-GateState {
    if (-not (Test-Path -LiteralPath $GatePath)) {
        throw "Active run gate is missing: $GatePath"
    }
    $json = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json
    if ($LASTEXITCODE -ne 0) { throw "Active run gate check failed with exit code $LASTEXITCODE." }
    return ((@($json) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Assert-GateOpen {
    param([Parameter(Mandatory = $true)]$Gate)
    $status = if ($Gate.gate_status) { [string]$Gate.gate_status } else { [string]$Gate.status }
    if ($status -eq "RUNNING") {
        throw "Execution probe blocked by active gate status=RUNNING, run_id=$($Gate.run_id)."
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before starting an execution probe."
    }
}

function Set-OwnedFailure {
    param([Parameter(Mandatory = $true)][string]$Failure)
    foreach ($path in @($GatePath, $CurrentRunPath) | Select-Object -Unique) {
        if (Test-Path -LiteralPath $path) {
            $document = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            $status = if ($document.gate_status) { [string]$document.gate_status } else { [string]$document.status }
            if ($status -eq "RUNNING" -and [string]$document.run_id -ne $RunId) { continue }
        } else {
            $document = [pscustomobject]@{ schema = "active_run_gate_v2"; project = "trading_mvp" }
        }
        foreach ($entry in @(
            @("run_id", $RunId),
            @("status", "STOPPED_INCOMPLETE"),
            @("gate_status", "STOPPED_INCOMPLETE"),
            @("final", $false),
            @("collector_pid", $null),
            @("process_ids", @()),
            @("failure", $Failure),
            @("stop_reason", "basis_v2_execution_probe_visible_worker_failed"),
            @("manifest_path", $ManifestPath),
            @("replay_allowed", $false),
            @("paper_forward_allowed", $false),
            @("updated_at", [DateTimeOffset]::Now.ToString("o"))
        )) {
            Set-ObjectProperty -Object $document -Name $entry[0] -Value $entry[1]
        }
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

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "Historical basis v2 execution probe plan is missing: $PlanPath"
}
$PlanPath = (Resolve-Path -LiteralPath $PlanPath).Path
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$RunDirectory = Join-Path $OutputRoot $RunId
$SamplesPath = Join-Path $RunDirectory "samples.jsonl"
$ManifestPath = Join-Path $RunDirectory "manifest.json"
$python = Resolve-Python
$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
$validator = Resolve-Validator -Plan $plan
$validationRaw = & $python $validator validate-plan --plan $PlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Execution probe plan validation failed." }
$validation = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
if ([string]$validation.probe_plan_hash -ne $ExpectedPlanHash) {
    throw "Validated probe plan hash does not match ExpectedPlanHash."
}
$window = @($plan.windows | Where-Object { [int]$_.index -eq $WindowIndex })[0]
if (-not $window) { throw "WindowIndex=$WindowIndex is absent from the probe plan." }

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
        [string]$launch.probe_plan_hash -ne $ExpectedPlanHash -or
        [int]$launch.window_index -ne $WindowIndex
    ) {
        throw "Worker launch record does not match the requested probe window."
    }
    $env:PYTHONUNBUFFERED = "1"
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp basis-v2 execution probe - $RunId" } catch { }
    Update-LaunchRecord -Values @{
        status = "RUNNING"
        worker_pid = $PID
        worker_started_at = [DateTimeOffset]::Now.ToString("o")
    }
    Write-Host "trading_mvp basis-v2 visible execution-capacity probe" -ForegroundColor Cyan
    Write-Host "run_id=$RunId"
    Write-Host "probe_plan_hash=$ExpectedPlanHash"
    Write-Host "window=$WindowIndex start=$($window.start_utc) end=$($window.end_utc)"
    Write-Host "samples_path=$SamplesPath"
    Write-Host "manifest_path=$ManifestPath"
    try {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $RunMvp `
            -Action fast-edge-basis-v2-execution-probe `
            -PlanPath $PlanPath -ExpectedPlanHash $ExpectedPlanHash -WindowIndex $WindowIndex `
            -OutputPath $SamplesPath -ManifestPath $ManifestPath -RunId $RunId `
            -ActiveRunGatePath $GatePath -MaxRuntimeSec $MaxRuntimeSec 2>&1 |
            Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) { throw "run_mvp exited with code $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $ManifestPath)) {
            throw "Execution probe exited without manifest: $ManifestPath"
        }
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        if ($manifest.final -ne $true) { throw "Execution probe manifest is not final." }
        Update-LaunchRecord -Values @{
            status = "COMPLETED"
            completed_at = [DateTimeOffset]::Now.ToString("o")
            manifest_path = $ManifestPath
            manifest_result_hash = [string]$manifest.deterministic_result_hash
            worker_exit_code = 0
        }
        Write-Host "READY_FOR_POSTPROCESS window=$WindowIndex" -ForegroundColor Green
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        try { Set-OwnedFailure -Failure $message } catch { }
        Update-LaunchRecord -Values @{
            status = "STOPPED_INCOMPLETE"
            completed_at = [DateTimeOffset]::Now.ToString("o")
            failure = $message
            worker_exit_code = 1
        }
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Get-GateState
Assert-GateOpen -Gate $gate
$approvalPhrase = "Подтверждаю visible basis-v2 execution probe plan_hash=$ExpectedPlanHash, window=$WindowIndex, run_id=$RunId, MaxRuntimeSec=$MaxRuntimeSec, public API only, без grid/OOS/live/private API keys."
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -WindowIndex $WindowIndex -RunId $RunId -OutputRoot `"$OutputRoot`" -GatePath `"$GatePath`" -CurrentRunPath `"$CurrentRunPath`" -LaunchRecordPath `"$LaunchRecordPath`" -LogPath `"$LogPath`" -MaxRuntimeSec $MaxRuntimeSec -HoldOpenSec $HoldOpenSec -ConfirmedExecutionProbe"

if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_basis_v2_execution_probe_visible_preview_v1"
        mode = "PlanOnly"
        decision = "AWAIT_EXPLICIT_BASIS_V2_EXECUTION_PROBE_APPROVAL"
        plan_path = $PlanPath
        probe_plan_hash = $ExpectedPlanHash
        window_index = $WindowIndex
        window_start_utc = [string]$window.start_utc
        window_end_utc = [string]$window.end_utc
        duration_sec = [int]$plan.duration_sec
        interval_sec = [int]$plan.interval_sec
        run_id = $RunId
        output_root = $OutputRoot
        samples_path = $SamplesPath
        manifest_path = $ManifestPath
        max_runtime_sec = $MaxRuntimeSec
        gate_status = $(if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status })
        visible_terminal_required = $true
        network_access = $false
        collector_started = $false
        live_orders = $false
        private_api_keys = $false
        leverage_or_margin = $false
        grid_search = $false
        approval_phrase = $approvalPhrase
        approval_command = $approvalCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}

if (-not $ConfirmedExecutionProbe) {
    throw "ConfirmedExecutionProbe is required for an actual execution probe. Run -PlanOnly first."
}
$windowStart = [DateTimeOffset]::Parse([string]$window.start_utc)
$windowEnd = [DateTimeOffset]::Parse([string]$window.end_utc)
$now = [DateTimeOffset]::UtcNow
if ($now -ge $windowEnd) {
    throw "The approved execution probe window has already ended."
}
if ($now -gt $windowStart.AddSeconds([int]$plan.interval_sec)) {
    throw "The approved execution probe window start was missed."
}
$countdownSec = [Math]::Max(0, ($windowStart - $now).TotalSeconds)
if ($countdownSec + [int]$plan.duration_sec -gt $MaxRuntimeSec) {
    throw "MaxRuntimeSec does not cover the countdown plus frozen probe duration."
}
if (Test-Path -LiteralPath $RunDirectory) {
    throw "Refusing to overwrite existing probe run directory: $RunDirectory"
}
if (Test-Path -LiteralPath $LaunchRecordPath) {
    throw "Refusing to overwrite immutable visible launch record: $LaunchRecordPath"
}

$token = [Guid]::NewGuid().ToString("N")
$launchRecord = [ordered]@{
    schema = "trading_mvp_basis_v2_execution_probe_visible_launch_v1"
    status = "LAUNCHING"
    run_id = $RunId
    plan_path = $PlanPath
    probe_plan_hash = $ExpectedPlanHash
    window_index = $WindowIndex
    window_start_utc = [string]$window.start_utc
    window_end_utc = [string]$window.end_utc
    samples_path = $SamplesPath
    manifest_path = $ManifestPath
    log_path = $LogPath
    max_runtime_sec = $MaxRuntimeSec
    worker_token_sha256 = Get-TextSha256 -Value $token
    created_at = [DateTimeOffset]::Now.ToString("o")
    visible_terminal = $true
    public_api_only = $true
    live = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord

$script = @(
    "& $(Quote-PowerShellLiteral -Value $PSCommandPath)",
    "-PlanPath $(Quote-PowerShellLiteral -Value $PlanPath)",
    "-ExpectedPlanHash $(Quote-PowerShellLiteral -Value $ExpectedPlanHash)",
    "-WindowIndex $WindowIndex",
    "-RunId $(Quote-PowerShellLiteral -Value $RunId)",
    "-OutputRoot $(Quote-PowerShellLiteral -Value $OutputRoot)",
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
$process = Start-Process -FilePath $pwsh -ArgumentList @("-NoProfile", "-EncodedCommand", $encoded) -WindowStyle Normal -PassThru
Update-LaunchRecord -Values @{
    status = "STARTED"
    launcher_pid = $PID
    worker_pid = $process.Id
    started_at = [DateTimeOffset]::Now.ToString("o")
}
[ordered]@{
    decision = "VISIBLE_BASIS_V2_EXECUTION_PROBE_STARTED"
    run_id = $RunId
    probe_plan_hash = $ExpectedPlanHash
    window_index = $WindowIndex
    worker_pid = $process.Id
    samples_path = $SamplesPath
    manifest_path = $ManifestPath
    launch_record_path = $LaunchRecordPath
    log_path = $LogPath
    visible_terminal = $true
} | ConvertTo-Json -Depth 8
