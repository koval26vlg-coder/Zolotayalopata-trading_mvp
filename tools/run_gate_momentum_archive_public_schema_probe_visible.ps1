param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$DescriptorPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 300)][int]$MaxRuntimeSec = 120,
    [ValidateRange(1, 60)][int]$TimeoutSec = 15,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60,
    [string]$ProjectRoot = "C:\Users\koval\Documents\ZolotyayLopata",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [switch]$ConfirmedGateMomentumPublicSchemaProbe
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$Module = Join-Path $RepoRoot "trading_mvp\src\gate_momentum_archive.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $CurrentRunPath) { $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json" }

if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$") {
    throw "RunId contains unsupported characters."
}
if ($ExpectedPlanHash -notmatch "^[0-9a-f]{64}$") {
    throw "ExpectedPlanHash must be a lowercase SHA-256 digest."
}
if (-not $ConfirmedGateMomentumPublicSchemaProbe) {
    throw "Actual network probe requires -ConfirmedGateMomentumPublicSchemaProbe."
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$DescriptorPath = [System.IO.Path]::GetFullPath($DescriptorPath)
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\runs\$RunId.launch.json"
}
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
if (-not $LogPath) {
    $LogPath = Join-Path (Split-Path -Parent $OutputPath) "$RunId.visible.log"
}
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$StdoutPath = "$LogPath.stdout"
$StderrPath = "$LogPath.stderr"
$runStartedAt = [DateTimeOffset]::Now

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) { return [System.IO.Path]::GetFullPath($candidate) }
    }
    throw "Python runtime with requests was not found. Set TRADING_MVP_PYTHON."
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
        $Value | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function ConvertTo-CommandLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Set-Property {
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

function Update-RunState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$Final,
        [int]$Errors = 0,
        [string]$Decision = "",
        [string]$GoalReason = "",
        [string]$NextStep = "",
        [string]$StopReason = "",
        [int]$WorkerPid = 0
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
    $processIds = if ($Status -eq "RUNNING") { @($PID, $WorkerPid) | Where-Object { $_ -gt 0 } } else { @() }
    $now = [DateTimeOffset]::Now
    $locks = if ($Status -eq "RUNNING") {
        [pscustomobject]@{
            market_data_writer = $RunId
            output_prefix = (Split-Path -Parent $OutputPath)
        }
    } else {
        [pscustomobject]@{}
    }
    foreach ($entry in @(
        @("run_id", $RunId),
        @("run_type", "gate_momentum_tardis_public_schema_probe"),
        @("status", $Status),
        @("gate_status", $Status),
        @("final", $Final),
        @("created_at", $runStartedAt.ToString("o")),
        @("started_at", $runStartedAt.ToString("o")),
        @("updated_at", $now.ToString("o")),
        @("completed_at", $(if ($Final) { $now.ToString("o") } else { $null })),
        @("requested_duration_sec", $MaxRuntimeSec),
        @(
            "actual_duration_sec",
            $(if ($Final) { [Math]::Max(0.0, ($now - $runStartedAt).TotalSeconds) } else { $null })
        ),
        @("expected_end_at", $runStartedAt.AddSeconds($MaxRuntimeSec).ToString("o")),
        @("manifest_path", $OutputPath),
        @("output_path", $OutputPath),
        @("output", [pscustomobject]@{ path = $OutputPath; kind = "file" }),
        @(
            "expected_outputs",
            [pscustomobject]@{
                result = $OutputPath
                launch_record = $LaunchRecordPath
            }
        ),
        @("completed_cycles", $(if ($Final) { 1 } else { 0 })),
        @("total_cycles", 1),
        @("remaining_cycles", $(if ($Final) { 0 } else { 1 })),
        @("errors", $Errors),
        @("primary_output_complete", $Final),
        @("expected_outputs_complete", $Final),
        @("monitor_pid", $(if ($Status -eq "RUNNING") { $PID } else { $null })),
        @("collector_pid", $(if ($Status -eq "RUNNING" -and $WorkerPid -gt 0) { $WorkerPid } else { $null })),
        @("process_ids", $processIds),
        @("stop_reason", $StopReason),
        @("resume_command", $null),
        @("next_goal_decision", $Decision),
        @("next_goal_reason", $GoalReason),
        @("next_step_after_ready", $NextStep),
        @("purpose", "Bounded public Gate archive schema probe for the frozen momentum source contract."),
        @("replay_allowed", $false),
        @("grid_allowed", $false),
        @("backtest_allowed", $false),
        @("execution_probe_allowed", $false),
        @("paper_forward_allowed", $false),
        @("live_orders", $false),
        @("private_api_keys", $false),
        @("leverage_or_margin", $false),
        @("owner_output_prefix", (Split-Path -Parent $OutputPath)),
        @("code_snapshot_hash", $moduleHash),
        @("launch_record_path", $LaunchRecordPath),
        @("current_run_pointer_path", $CurrentRunPath),
        @("locks", $locks),
        @("parallel_safe_actions", @("unit_tests_on_other_immutable_cache", "static_analysis")),
        @("forbidden_overlapping_actions", @(
            "second_market_data_writer",
            "consumer_of_incomplete_output",
            "grid_search",
            "oos",
            "live_orders"
        ))
    )) {
        Set-Property -Object $gate -Name $entry[0] -Value $entry[1]
    }
    Write-JsonAtomic -Path $GatePath -Value $gate

    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = $RunId
        status = $Status
        updated_at = $now.ToString("o")
        manifest_path = $OutputPath
        output = [ordered]@{ path = $OutputPath; kind = "file" }
        collector_pid = $(if ($Status -eq "RUNNING" -and $WorkerPid -gt 0) { $WorkerPid } else { $null })
        monitor_pid = $(if ($Status -eq "RUNNING") { $PID } else { $null })
        process_ids = $processIds
        launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

function Show-NewLogLines {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ref]$Seen,
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $lines = @(Get-Content -LiteralPath $Path)
    if ($lines.Count -gt $Seen.Value) {
        foreach ($line in ($lines | Select-Object -Skip $Seen.Value)) {
            Write-Host $line -ForegroundColor $Color
        }
        $Seen.Value = $lines.Count
    }
}

foreach ($required in @($Module, $GateChecker, $PlanPath, $DescriptorPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file is missing: $required"
    }
}
if (Test-Path -LiteralPath $OutputPath) {
    throw "Immutable probe output already exists: $OutputPath"
}
if (Test-Path -LiteralPath $LaunchRecordPath) {
    throw "Immutable launch record already exists: $LaunchRecordPath"
}

$gateStatus = & $GateChecker -Json | ConvertFrom-Json
if ([string]$gateStatus.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    throw "Active-run gate is $($gateStatus.status) for run_id=$($gateStatus.run_id). Resolve it first."
}
if (@($gateStatus.live_process_ids).Count -gt 0) {
    throw "Active-run checker found live owner processes."
}

$Python = Resolve-Python
& $Python -u $Module validate-probe-descriptor `
    --plan $PlanPath `
    --descriptor $DescriptorPath `
    --expected-plan-hash $ExpectedPlanHash | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Hash-bound public schema probe preflight failed."
}

foreach ($path in @($OutputPath, $LogPath, $StdoutPath, $StderrPath, $LaunchRecordPath)) {
    $parent = Split-Path -Parent $path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
}

$moduleHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Module).Hash.ToLowerInvariant()
$descriptorHash = [string]((Get-Content -LiteralPath $DescriptorPath -Raw | ConvertFrom-Json).descriptor_hash)
$launchCommand = @(
    "pwsh"
    "-NoProfile"
    "-ExecutionPolicy"
    "Bypass"
    "-File"
    (ConvertTo-CommandLiteral -Value $PSCommandPath)
    "-PlanPath"
    (ConvertTo-CommandLiteral -Value $PlanPath)
    "-DescriptorPath"
    (ConvertTo-CommandLiteral -Value $DescriptorPath)
    "-ExpectedPlanHash"
    $ExpectedPlanHash
    "-OutputPath"
    (ConvertTo-CommandLiteral -Value $OutputPath)
    "-RunId"
    $RunId
    "-MaxRuntimeSec"
    [string]$MaxRuntimeSec
    "-TimeoutSec"
    [string]$TimeoutSec
    "-HoldOpenSec"
    [string]$HoldOpenSec
    "-ProjectRoot"
    (ConvertTo-CommandLiteral -Value $ProjectRoot)
    "-GatePath"
    (ConvertTo-CommandLiteral -Value $GatePath)
    "-CurrentRunPath"
    (ConvertTo-CommandLiteral -Value $CurrentRunPath)
    "-LaunchRecordPath"
    (ConvertTo-CommandLiteral -Value $LaunchRecordPath)
    "-LogPath"
    (ConvertTo-CommandLiteral -Value $LogPath)
    "-ConfirmedGateMomentumPublicSchemaProbe"
) -join " "
$launchRecord = [ordered]@{
    schema = "active_run_launch_record_v1"
    project = "trading_mvp"
    run_id = $RunId
    run_type = "gate_momentum_tardis_public_schema_probe"
    created_at = $runStartedAt.ToString("o")
    command = $launchCommand
    cwd = $ProjectRoot
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    descriptor_path = $DescriptorPath
    descriptor_hash = $descriptorHash
    output_path = $OutputPath
    log_path = $LogPath
    stdout_path = $StdoutPath
    stderr_path = $StderrPath
    max_runtime_sec = $MaxRuntimeSec
    timeout_sec = $TimeoutSec
    code_snapshot_hash = $moduleHash
    research_only = $true
    public_api_only = $true
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord

$arguments = @(
    "-u",
    $Module,
    "public-schema-probe",
    "--plan", $PlanPath,
    "--descriptor", $DescriptorPath,
    "--expected-plan-hash", $ExpectedPlanHash,
    "--timeout-sec", [string]$TimeoutSec,
    "--output", $OutputPath
)

$worker = $null
$exitCode = 1
$seenOut = 0
$seenErr = 0
try {
    Write-Host "[gate-momentum-archive] visible public schema probe starting" -ForegroundColor Cyan
    Write-Host "[gate-momentum-archive] run_id=$RunId"
    Write-Host "[gate-momentum-archive] output=$OutputPath"
    Write-Host "[gate-momentum-archive] max_runtime_sec=$MaxRuntimeSec"
    $worker = Start-Process -FilePath $Python -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
    Update-RunState -Status "RUNNING" -Final $false `
        -Decision "GATE_MOMENTUM_PUBLIC_SCHEMA_PROBE_RUNNING" `
        -GoalReason "Visible bounded public schema probe is running." `
        -NextStep "Wait for the visible bounded schema probe to finish." `
        -WorkerPid $worker.Id
    $deadline = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec)
    while (-not $worker.HasExited) {
        Show-NewLogLines -Path $StdoutPath -Seen ([ref]$seenOut)
        Show-NewLogLines -Path $StderrPath -Seen ([ref]$seenErr) -Color Red
        $remaining = [Math]::Max(0, [int][Math]::Ceiling(($deadline - [DateTimeOffset]::Now).TotalSeconds))
        Write-Host ("[gate-momentum-archive] pid={0} remaining_sec={1}" -f $worker.Id, $remaining)
        if ([DateTimeOffset]::Now -ge $deadline) {
            Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
            throw "Public schema probe exceeded MaxRuntimeSec=$MaxRuntimeSec."
        }
        Start-Sleep -Seconds 1
        $worker.Refresh()
    }
    Show-NewLogLines -Path $StdoutPath -Seen ([ref]$seenOut)
    Show-NewLogLines -Path $StderrPath -Seen ([ref]$seenErr) -Color Red
    $exitCode = $worker.ExitCode
    if ($exitCode -ne 0) {
        throw "Public schema probe worker failed with exit code $exitCode."
    }
    if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
        throw "Public schema probe output was not created."
    }
    $report = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
    if (
        $report.final -ne $true -or
        [string]$report.plan_hash -ne $ExpectedPlanHash -or
        [string]$report.descriptor_hash -ne $descriptorHash -or
        [string]$report.artifact_hash -notmatch "^[0-9a-f]{64}$"
    ) {
        throw "Public schema probe result failed final/hash validation."
    }
    $launchRecord.status = "READY_FOR_POSTPROCESS"
    $launchRecord.final = $true
    $launchRecord.completed_at = [DateTimeOffset]::Now.ToString("o")
    $launchRecord.worker_exit_code = $exitCode
    $launchRecord.verdict = [string]$report.verdict
    $launchRecord.artifact_hash = [string]$report.artifact_hash
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord
    $resultReason = if ($report.failure -and $report.failure.message) {
        [string]$report.failure.message
    } else {
        [string](@($report.reason_codes) -join ",")
    }
    Update-RunState -Status "READY_FOR_POSTPROCESS" -Final $true `
        -Decision ([string]$report.verdict) `
        -GoalReason $resultReason `
        -NextStep ([string]$report.next_allowed_command)
    Write-Host ("[gate-momentum-archive] final verdict={0}" -f $report.verdict) -ForegroundColor Green
} catch {
    $message = $_.Exception.Message
    if ($worker -and -not $worker.HasExited) {
        Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
    }
    $launchRecord.status = "STOPPED_INCOMPLETE"
    $launchRecord.final = $false
    $launchRecord.completed_at = [DateTimeOffset]::Now.ToString("o")
    $launchRecord.worker_exit_code = 1
    $launchRecord.failure = $message
    Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord
    Update-RunState -Status "STOPPED_INCOMPLETE" -Final $false -Errors 1 `
        -Decision "GATE_MOMENTUM_PUBLIC_SCHEMA_PROBE_STOPPED_INCOMPLETE" `
        -GoalReason $message `
        -NextStep "Inspect logs, then resume only with explicit approval or reject the incomplete run." `
        -StopReason $message
    Write-Host "[gate-momentum-archive] STOPPED_INCOMPLETE: $message" -ForegroundColor Red
    $exitCode = 1
}

@(
    "[$([DateTimeOffset]::Now.ToString('o'))] run_id=$RunId"
    "status=$(if ($exitCode -eq 0) { 'READY_FOR_POSTPROCESS' } else { 'STOPPED_INCOMPLETE' })"
    "stdout=$StdoutPath"
    "stderr=$StderrPath"
) | Set-Content -LiteralPath $LogPath -Encoding UTF8

if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit $exitCode
