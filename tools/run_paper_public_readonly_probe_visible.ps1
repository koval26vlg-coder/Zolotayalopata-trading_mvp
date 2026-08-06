param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$AuthorizationPath,
    [Parameter(Mandatory = $true)][string]$ExpectedAuthorizationHash,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 180)][int]$MaxRuntimeSec = 180,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 45,
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProbeModule = Join-Path $ProjectRoot "trading_mvp\src\paper_public_readonly_probe.py"
$PostrunScript = Join-Path $ProjectRoot "tools\run_trading_mvp_public_readonly_probe_postrun.ps1"
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json"
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$AuthorizationPath = [System.IO.Path]::GetFullPath($AuthorizationPath)
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
if ($LaunchRecordPath) {
    $LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
}
if (-not $LogPath) {
    $LogPath = Join-Path $OutputDir "visible.log"
}
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$ManifestPath = Join-Path $OutputDir "manifest.json"
$SnapshotsPath = Join-Path $OutputDir "snapshots.jsonl"
$ErrorsPath = Join-Path $OutputDir "errors.jsonl"
$PlanDocument = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
$PlanVersion = switch ([string]$PlanDocument.schema) {
    "trading_mvp_paper_public_readonly_probe_plan_v3" { "v3"; break }
    "trading_mvp_paper_public_readonly_probe_plan_v2" { "v2"; break }
    default { "v1" }
}
$AuthorizationDocument = Get-Content -LiteralPath $AuthorizationPath -Raw |
    ConvertFrom-Json
$AuthorizationBasis = if (
    $AuthorizationDocument.PSObject.Properties.Name -contains
        "authorization_basis"
) {
    [string]$AuthorizationDocument.authorization_basis
} else {
    "explicit_user_instruction_in_current_thread"
}
$EvidencePath = (
    "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\" +
    "paper-public-readonly-probe-evidence-$PlanVersion.json"
)

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
    throw "Python runtime with requests is unavailable. Set TRADING_MVP_PYTHON."
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
        $Value | ConvertTo-Json -Depth 50 |
            Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
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

function Read-LaunchRecord {
    if (
        $LaunchRecordPath -and
        (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)
    ) {
        return (
            Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
        )
    }
    return $null
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    $record = Read-LaunchRecord
    if ($null -eq $record) { return }
    foreach ($entry in $Values.GetEnumerator()) {
        Set-Property -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

$PriorApprovedNightSchedule = $null
if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
    $priorGate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
    if ($priorGate.PSObject.Properties.Name -contains "approved_night_schedule") {
        $PriorApprovedNightSchedule = $priorGate.approved_night_schedule
    }
}

function Set-RunState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$Final,
        [int]$CompletedCycles = 0,
        [int]$Rows = 0,
        [int]$Errors = 0,
        [double]$ActualDurationSec = 0.0,
        [string]$NextDecision = "",
        [string]$Reason = "",
        [string]$StopReason = "",
        [switch]$AllowInitialSupersede
    )
    if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
        $existing = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
        $existingStatus = if ($existing.gate_status) {
            [string]$existing.gate_status
        } else {
            [string]$existing.status
        }
        $allowedSupersededRunId = switch ($PlanVersion) {
            "v2" { "paper_public_readonly_probe_20260730_142851"; break }
            "v3" { "paper_public_readonly_probe_v2_20260730_145817"; break }
            default { "" }
        }
        if (
            [string]$existing.run_id -ne $RunId -and
            (
                -not $AllowInitialSupersede -or
                $existingStatus -eq "RUNNING" -or
                [string]$existing.run_id -ne $allowedSupersededRunId
            )
        ) {
            throw "Refusing to overwrite gate owned by run_id=$($existing.run_id)."
        }
    }
    $now = [DateTimeOffset]::Now
    $processIds = if ($Status -eq "RUNNING") { @($PID) } else { @() }
    $launchRecord = Read-LaunchRecord
    $postrunCommand = @(
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PostrunScript`"",
        "-ManifestPath `"$ManifestPath`"",
        "-ExpectedPlanHash `"$ExpectedPlanHash`"",
        "-EvidencePath `"$EvidencePath`""
    ) -join " "
    $gate = [ordered]@{
        schema = "active_run_gate_v2"
        project = "trading_mvp"
        run_id = $RunId
        run_type = "paper_public_readonly_probe"
        purpose = "Frozen bounded public REST reliability probe for paper-product readiness."
        status = $Status
        gate_status = $Status
        final = $Final
        created_at = if ($launchRecord.created_at) {
            [string]$launchRecord.created_at
        } else {
            $now.ToString("o")
        }
        updated_at = $now.ToString("o")
        completed_at = if ($Status -eq "RUNNING") { $null } else { $now.ToString("o") }
        requested_duration_sec = 120
        max_runtime_sec = $MaxRuntimeSec
        actual_duration_sec = $ActualDurationSec
        expected_end_at = $now.AddSeconds($MaxRuntimeSec).ToString("o")
        completed_cycles = $CompletedCycles
        total_cycles = 24
        remaining_cycles = [Math]::Max(0, 24 - $CompletedCycles)
        rows = $Rows
        errors = $Errors
        primary_output_complete = $Final
        expected_outputs_complete = $Final
        stop_reason = $StopReason
        collector_pid = if ($Status -eq "RUNNING") { $PID } else { $null }
        monitor_pid = $null
        process_ids = $processIds
        manifest_path = $ManifestPath
        output_path = $SnapshotsPath
        output = [ordered]@{ path = $SnapshotsPath; kind = "file" }
        expected_outputs = [ordered]@{
            manifest = $ManifestPath
            snapshots = $SnapshotsPath
            errors = $ErrorsPath
        }
        plan_path = $PlanPath
        plan_hash_sha256 = $ExpectedPlanHash
        authorization_path = $AuthorizationPath
        authorization_hash_sha256 = $ExpectedAuthorizationHash
        authorization_action = "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE"
        authorization_basis = $AuthorizationBasis
        standing_authorization_path = if (
            $launchRecord -and
            $launchRecord.standing_authorization_path
        ) {
            [string]$launchRecord.standing_authorization_path
        } else {
            $null
        }
        standing_authorization_hash_sha256 = if (
            $launchRecord -and
            $launchRecord.standing_authorization_hash_sha256
        ) {
            [string]$launchRecord.standing_authorization_hash_sha256
        } else {
            $null
        }
        critical_authorization_path = if (
            $launchRecord -and
            $launchRecord.critical_authorization_path
        ) {
            [string]$launchRecord.critical_authorization_path
        } else {
            $null
        }
        critical_authorization_hash_sha256 = if (
            $launchRecord -and
            $launchRecord.critical_authorization_hash_sha256
        ) {
            [string]$launchRecord.critical_authorization_hash_sha256
        } else {
            $null
        }
        freshness_failure_audit_path = if (
            $launchRecord -and
            $launchRecord.freshness_failure_audit_path
        ) {
            [string]$launchRecord.freshness_failure_audit_path
        } else {
            $null
        }
        launch_record_path = $LaunchRecordPath
        log_path = $LogPath
        prior_gate_archive_path = if ($launchRecord) {
            [string]$launchRecord.prior_gate_archive_path
        } else {
            $null
        }
        prior_pointer_archive_path = if ($launchRecord) {
            [string]$launchRecord.prior_pointer_archive_path
        } else {
            $null
        }
        public_api_only = $true
        maximum_public_get_attempts = 576
        auto_resume = $false
        resume_command = $null
        replay_allowed = $false
        grid_allowed = $false
        backtest_allowed = $false
        execution_probe_allowed = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        private_api_keys = $false
        leverage_or_margin = $false
        next_goal_decision = $NextDecision
        next_goal_reason = $Reason
        next_step_after_ready = if ($Final) {
            $postrunCommand
        } else {
            "Status-only until this visible public read-only probe finishes."
        }
        postprocess_command = if ($Final) { $postrunCommand } else { $null }
        parallel_safe_actions = @(
            "unit_tests_on_other_immutable_cache",
            "static_analysis"
        )
        forbidden_overlapping_actions = @(
            "second_market_data_writer",
            "consumer_of_incomplete_output",
            "grid_search",
            "oos",
            "paper_forward",
            "live_orders"
        )
    }
    if ($null -ne $PriorApprovedNightSchedule) {
        $gate["approved_night_schedule"] = $PriorApprovedNightSchedule
    }
    Write-JsonAtomic -Path $GatePath -Value $gate
    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = $RunId
        status = $Status
        updated_at = $now.ToString("o")
        manifest_path = $ManifestPath
        output = [ordered]@{ path = $SnapshotsPath; kind = "file" }
        collector_pid = if ($Status -eq "RUNNING") { $PID } else { $null }
        monitor_pid = $null
        process_ids = $processIds
        launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

foreach ($required in @(
    $ProbeModule,
    $PostrunScript,
    $PlanPath,
    $AuthorizationPath,
    $LaunchRecordPath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required public probe file is missing: $required"
    }
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    throw "RunId is required."
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.Length -ne 64) {
    throw "Frozen plan file hash is unavailable."
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) |
    Out-Null
$Python = Resolve-Python
$env:TRADING_MVP_PYTHON = $Python

Update-LaunchRecord -Values @{
    status = "RUNNING"
    gate_status = "RUNNING"
    worker_pid = $PID
    collector_pid = $PID
    process_ids = @($PID)
    worker_started_at = [DateTimeOffset]::Now.ToString("o")
}
Set-RunState -Status "RUNNING" -Final $false `
    -NextDecision "PUBLIC_READONLY_PROBE_RUNNING" `
    -Reason "One visible bounded public GET writer is running; overlapping writers and consumers are blocked." `
    -AllowInitialSupersede

$arguments = @(
    "-u", $ProbeModule, "probe",
    "--plan", $PlanPath,
    "--expected-plan-hash", $ExpectedPlanHash,
    "--authorization", $AuthorizationPath,
    "--expected-authorization-hash", $ExpectedAuthorizationHash,
    "--output-dir", $OutputDir,
    "--run-id", $RunId,
    "--max-runtime-sec", [string]$MaxRuntimeSec
)
$exitCode = 1
try {
    "[$(Get-Date -Format o)] visible public read-only probe start run_id=$RunId" |
        Tee-Object -FilePath $LogPath
    $null = & $Python @arguments 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    $probeExitCode = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Public probe manifest was not created: $ManifestPath"
    }
    $validationOutput = & $Python -u $ProbeModule validate-result `
        --manifest $ManifestPath `
        --expected-plan-hash $ExpectedPlanHash 2>&1
    $validationExitCode = $LASTEXITCODE
    @($validationOutput) | Add-Content -LiteralPath $LogPath -Encoding UTF8
    if ($validationExitCode -ne 0) {
        throw "Public probe result validation failed with exit code $validationExitCode."
    }
    $report = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ([string]$report.run_id -ne $RunId) {
        throw "Public probe manifest run id mismatch."
    }
    if (
        [string]$report.authorization.authorization_hash_sha256 -ne
        $ExpectedAuthorizationHash
    ) {
        throw "Public probe manifest authorization hash mismatch."
    }
    $rowCount = [int]$report.quality.snapshot_count
    $errorCount = [int]$report.quality.error_count
    $completedCycles = [int]$report.runtime.cycles_completed
    $actualDuration = [double]$report.runtime.elapsed_sec
    if ($report.final -eq $true -and $probeExitCode -eq 0) {
        $manifestFileHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $ManifestPath
        ).Hash.ToLowerInvariant()
        Update-LaunchRecord -Values @{
            status = "READY_FOR_POSTPROCESS"
            gate_status = "READY_FOR_POSTPROCESS"
            final = $true
            completed_at = [DateTimeOffset]::Now.ToString("o")
            worker_exit_code = 0
            collector_pid = $null
            process_ids = @()
            rows = $rowCount
            errors = $errorCount
            manifest_file_sha256 = $manifestFileHash
            deterministic_result_hash = [string]$report.deterministic_result_hash
            verdict = [string]$report.verdict
        }
        Set-RunState -Status "READY_FOR_POSTPROCESS" -Final $true `
            -CompletedCycles $completedCycles -Rows $rowCount `
            -Errors $errorCount -ActualDurationSec $actualDuration `
            -NextDecision "POSTPROCESS_PUBLIC_READONLY_PROBE_EVIDENCE" `
            -Reason "The bounded technical probe completed and passed immutable result validation." `
            -StopReason "completed"
        $exitCode = 0
    } else {
        $failure = if ($report.quality.hard_stop_reason) {
            [string]$report.quality.hard_stop_reason
        } else {
            "probe_result_not_final"
        }
        Update-LaunchRecord -Values @{
            status = "STOPPED_INCOMPLETE"
            gate_status = "STOPPED_INCOMPLETE"
            final = $false
            completed_at = [DateTimeOffset]::Now.ToString("o")
            worker_exit_code = $probeExitCode
            collector_pid = $null
            process_ids = @()
            rows = $rowCount
            errors = $errorCount
            failure = $failure
            verdict = [string]$report.verdict
        }
        Set-RunState -Status "STOPPED_INCOMPLETE" -Final $false `
            -CompletedCycles $completedCycles -Rows $rowCount `
            -Errors $errorCount -ActualDurationSec $actualDuration `
            -NextDecision "USER_REVIEW_REQUIRED_PUBLIC_READONLY_PROBE_STOPPED_INCOMPLETE" `
            -Reason "The one authorized public probe stopped incomplete; no automatic retry is permitted." `
            -StopReason $failure
        $exitCode = if ($probeExitCode -ne 0) { $probeExitCode } else { 2 }
    }
} catch {
    $message = $_.Exception.Message
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
        Set-RunState -Status "STOPPED_INCOMPLETE" -Final $false `
            -Errors 1 `
            -NextDecision "USER_REVIEW_REQUIRED_PUBLIC_READONLY_PROBE_STOPPED_INCOMPLETE" `
            -Reason "The one authorized public probe failed before producing validated complete evidence." `
            -StopReason $message
    } catch {
        "gate_update_failure=$($_.Exception.Message)" |
            Add-Content -LiteralPath $LogPath -Encoding UTF8
    }
    $message | Tee-Object -FilePath $LogPath -Append
    $exitCode = 1
}
"[$(Get-Date -Format o)] visible public read-only probe exit_code=$exitCode" |
    Tee-Object -FilePath $LogPath -Append
if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit $exitCode
