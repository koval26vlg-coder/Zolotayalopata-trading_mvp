Set-StrictMode -Version Latest

function Resolve-OwnedMetadataPython {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime with requests was not found. Set TRADING_MVP_PYTHON."
}

function Write-OwnedMetadataJsonAtomic {
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
        $Value | ConvertTo-Json -Depth 80 |
            Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Set-OwnedMetadataProperty {
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

function Show-OwnedMetadataNewLogLines {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ref]$Seen,
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }
    $lines = @(Get-Content -LiteralPath $Path)
    if ($lines.Count -le $Seen.Value) {
        return
    }
    foreach ($line in ($lines | Select-Object -Skip $Seen.Value)) {
        Write-Host $line -ForegroundColor $Color
    }
    $Seen.Value = $lines.Count
}

function Get-OwnedMetadataOutputStats {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    $stats = @()
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $stats += [pscustomobject]@{
                path = $path
                bytes = 0
                line_count = 0
                last_write = $null
            }
            continue
        }
        $item = Get-Item -LiteralPath $path
        $lineCount = 0
        if (
            $item.Length -gt 0 -and
            $item.Extension -in @(".jsonl", ".log", ".stdout", ".stderr")
        ) {
            $lineCount = @([System.IO.File]::ReadLines($item.FullName)).Count
        }
        $stats += [pscustomobject]@{
            path = $item.FullName
            bytes = $item.Length
            line_count = $lineCount
            last_write = $item.LastWriteTime.ToString("o")
        }
    }
    return $stats
}

function Invoke-VisibleOwnedMetadataCollect {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PlanPath,
        [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
        [Parameter(Mandatory = $true)][string]$ModulePath,
        [Parameter(Mandatory = $true)][string]$ResultPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$RunType,
        [Parameter(Mandatory = $true)][string]$CredentialEnvironmentVariable,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [ValidateRange(1, 600)][int]$MaxRuntimeSec = 120,
        [ValidateRange(0, 600)][int]$HoldOpenSec = 60,
        [string]$GatePath = "",
        [string]$CurrentRunPath = "",
        [string]$LaunchRecordPath = "",
        [string]$LogPath = ""
    )

    $ErrorActionPreference = "Stop"
    if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$") {
        throw "RunId contains unsupported characters."
    }
    if ($ExpectedPlanHash -notmatch "^[0-9a-f]{64}$") {
        throw "ExpectedPlanHash must be a lowercase SHA-256 digest."
    }
    if ($CredentialEnvironmentVariable -notmatch "^[A-Z][A-Z0-9_]{1,63}$") {
        throw "CredentialEnvironmentVariable is invalid."
    }

    $ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    $PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
    $ModulePath = [System.IO.Path]::GetFullPath($ModulePath)
    $ResultPath = [System.IO.Path]::GetFullPath($ResultPath)
    $GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
    if (-not $GatePath) {
        $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
    }
    if (-not $CurrentRunPath) {
        $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json"
    }
    if (-not $LaunchRecordPath) {
        $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\runs\$RunId.launch.json"
    }
    if (-not $LogPath) {
        $LogPath = Join-Path (Split-Path -Parent $ResultPath) "$RunId.visible.log"
    }
    $GatePath = [System.IO.Path]::GetFullPath($GatePath)
    $CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
    $LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
    $LogPath = [System.IO.Path]::GetFullPath($LogPath)
    $StdoutPath = "$LogPath.stdout"
    $StderrPath = "$LogPath.stderr"

    foreach ($required in @($PlanPath, $ModulePath, $GateChecker)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required file is missing: $required"
        }
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

    $credential = [Environment]::GetEnvironmentVariable(
        $CredentialEnvironmentVariable,
        "Process"
    )
    if ([string]::IsNullOrWhiteSpace($credential)) {
        throw "$CredentialEnvironmentVariable is not present in the process environment."
    }
    Remove-Variable credential

    $Python = Resolve-OwnedMetadataPython -ProjectRoot $ProjectRoot
    & $Python -u $ModulePath validate-plan --plan $PlanPath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Hash-bound plan validation failed."
    }
    $plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    if ([string]$plan.plan_hash -ne $ExpectedPlanHash) {
        throw "ExpectedPlanHash does not match the validated plan."
    }
    $frozenRuntime = [int]$plan.limits.max_runtime_sec
    if ($frozenRuntime -lt 1 -or $frozenRuntime -gt $MaxRuntimeSec) {
        throw "Frozen plan runtime $frozenRuntime exceeds wrapper MaxRuntimeSec=$MaxRuntimeSec."
    }

    $outputPaths = @()
    foreach ($property in $plan.outputs.PSObject.Properties) {
        if (
            $property.Name -eq "immutable" -or
            -not ($property.Value -is [string])
        ) {
            continue
        }
        $outputPaths += [System.IO.Path]::GetFullPath([string]$property.Value)
    }
    $outputPaths = @($outputPaths | Sort-Object -Unique)
    if ($ResultPath -notin $outputPaths) {
        throw "ResultPath is not one of the frozen plan outputs."
    }

    foreach ($path in @(
        $ResultPath,
        $LogPath,
        $StdoutPath,
        $StderrPath,
        $LaunchRecordPath,
        $GatePath,
        $CurrentRunPath
    )) {
        $parent = Split-Path -Parent $path
        if ($parent) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
    }

    $moduleHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ModulePath
    ).Hash.ToLowerInvariant()
    $launchRecord = [ordered]@{
        schema = "active_run_launch_record_v1"
        project = "trading_mvp"
        run_id = $RunId
        run_type = $RunType
        status = "PREFLIGHT_VALID"
        final = $false
        created_at = [DateTimeOffset]::Now.ToString("o")
        command = "python <module> collect --plan <plan>"
        cwd = $ProjectRoot
        plan_path = $PlanPath
        plan_hash = $ExpectedPlanHash
        module_path = $ModulePath
        result_path = $ResultPath
        output_paths = $outputPaths
        log_path = $LogPath
        stdout_path = $StdoutPath
        stderr_path = $StderrPath
        max_runtime_sec = $MaxRuntimeSec
        frozen_runtime_sec = $frozenRuntime
        credential_environment_variable = $CredentialEnvironmentVariable
        credential_value_persisted = $false
        code_snapshot_hash = $moduleHash
        research_only = $true
        metadata_only = $true
        live_orders = $false
        private_exchange_api_keys = $false
        leverage_or_margin = $false
    }
    Write-OwnedMetadataJsonAtomic -Path $LaunchRecordPath -Value $launchRecord

    function Update-OwnedMetadataRunState {
        param(
            [Parameter(Mandatory = $true)][string]$Status,
            [Parameter(Mandatory = $true)][bool]$Final,
            [int]$Errors = 0,
            [string]$Decision = "",
            [string]$NextStep = "",
            [string]$StopReason = "",
            [int]$WorkerPid = 0
        )

        if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
            $gate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
            $existingStatus = if ($gate.gate_status) {
                [string]$gate.gate_status
            } else {
                [string]$gate.status
            }
            if (
                $existingStatus -eq "RUNNING" -and
                [string]$gate.run_id -ne $RunId
            ) {
                throw "Refusing to overwrite active gate owned by run_id=$($gate.run_id)."
            }
        } else {
            $gate = [pscustomobject]@{
                schema = "active_run_gate_v2"
                project = "trading_mvp"
            }
        }

        $now = [DateTimeOffset]::Now
        $processIds = if ($Status -eq "RUNNING") {
            @($PID, $WorkerPid) | Where-Object { $_ -gt 0 }
        } else {
            @()
        }
        $locks = if ($Status -eq "RUNNING") {
            [pscustomobject]@{
                market_data_writer = $RunId
                output_prefix = (Split-Path -Parent $ResultPath)
            }
        } else {
            [pscustomobject]@{}
        }
        $stats = @(Get-OwnedMetadataOutputStats -Paths $outputPaths)
        $rowCount = ($stats | Measure-Object -Property line_count -Sum).Sum
        if ($null -eq $rowCount) {
            $rowCount = 0
        }
        $bytes = ($stats | Measure-Object -Property bytes -Sum).Sum
        if ($null -eq $bytes) {
            $bytes = 0
        }

        foreach ($entry in @(
            @("run_id", $RunId),
            @("run_type", $RunType),
            @("status", $Status),
            @("gate_status", $Status),
            @("final", $Final),
            @("updated_at", $now.ToString("o")),
            @("completed_at", $(if ($Final) { $now.ToString("o") } else { $null })),
            @("requested_duration_sec", $MaxRuntimeSec),
            @("expected_end_at", $now.AddSeconds($MaxRuntimeSec).ToString("o")),
            @("manifest_path", $ResultPath),
            @("output_path", $ResultPath),
            @("output", [pscustomobject]@{
                path = $ResultPath
                kind = "file"
                bytes = [int64]$bytes
                line_count = [int64]$rowCount
            }),
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
            @("next_step_after_ready", $NextStep),
            @("replay_allowed", $false),
            @("grid_allowed", $false),
            @("backtest_allowed", $false),
            @("execution_probe_allowed", $false),
            @("paper_forward_allowed", $false),
            @("live_orders", $false),
            @("private_api_keys", $false),
            @("leverage_or_margin", $false),
            @("owner_output_prefix", (Split-Path -Parent $ResultPath)),
            @("code_snapshot_hash", $moduleHash),
            @("launch_record_path", $LaunchRecordPath),
            @("current_run_pointer_path", $CurrentRunPath),
            @("locks", $locks),
            @("parallel_safe_actions", @(
                "unit_tests_on_other_immutable_cache",
                "static_analysis"
            )),
            @("forbidden_overlapping_actions", @(
                "second_market_data_writer",
                "consumer_of_incomplete_output",
                "grid_search",
                "oos",
                "live_orders"
            ))
        )) {
            Set-OwnedMetadataProperty `
                -Object $gate `
                -Name $entry[0] `
                -Value $entry[1]
        }
        Write-OwnedMetadataJsonAtomic -Path $GatePath -Value $gate

        $pointer = [ordered]@{
            schema = "active_run_pointer_v1"
            project = "trading_mvp"
            run_id = $RunId
            status = $Status
            updated_at = $now.ToString("o")
            manifest_path = $ResultPath
            output = [ordered]@{ path = $ResultPath; kind = "file" }
            collector_pid = $(if ($Status -eq "RUNNING" -and $WorkerPid -gt 0) { $WorkerPid } else { $null })
            monitor_pid = $(if ($Status -eq "RUNNING") { $PID } else { $null })
            process_ids = $processIds
            launch_record_path = $LaunchRecordPath
        }
        Write-OwnedMetadataJsonAtomic -Path $CurrentRunPath -Value $pointer
    }

    $arguments = @(
        "-u",
        $ModulePath,
        "collect",
        "--plan",
        $PlanPath
    )
    $worker = $null
    $runStateOwned = $false
    $exitCode = 1
    $seenOut = 0
    $seenErr = 0
    try {
        Write-Host "[$RunType] visible metadata collect starting" -ForegroundColor Cyan
        Write-Host "[$RunType] run_id=$RunId"
        Write-Host "[$RunType] result=$ResultPath"
        Write-Host "[$RunType] max_runtime_sec=$MaxRuntimeSec"
        Write-Host "[$RunType] credential=$CredentialEnvironmentVariable (value hidden)"

        $worker = Start-Process -FilePath $Python -ArgumentList $arguments -PassThru `
            -WindowStyle Hidden -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath
        Update-OwnedMetadataRunState -Status "RUNNING" -Final $false `
            -Decision "$($RunType.ToUpperInvariant())_RUNNING" `
            -NextStep "Wait for the visible bounded metadata collector to finish." `
            -WorkerPid $worker.Id
        $runStateOwned = $true
        $launchRecord.status = "RUNNING"
        $launchRecord.started_at = [DateTimeOffset]::Now.ToString("o")
        $launchRecord.worker_pid = $worker.Id
        Write-OwnedMetadataJsonAtomic -Path $LaunchRecordPath -Value $launchRecord

        $deadline = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec)
        while (-not $worker.HasExited) {
            Show-OwnedMetadataNewLogLines -Path $StdoutPath -Seen ([ref]$seenOut)
            Show-OwnedMetadataNewLogLines `
                -Path $StderrPath `
                -Seen ([ref]$seenErr) `
                -Color Red
            $remaining = [Math]::Max(
                0,
                [int][Math]::Ceiling(
                    ($deadline - [DateTimeOffset]::Now).TotalSeconds
                )
            )
            $stats = @(Get-OwnedMetadataOutputStats -Paths $outputPaths)
            $bytes = ($stats | Measure-Object -Property bytes -Sum).Sum
            $rows = ($stats | Measure-Object -Property line_count -Sum).Sum
            Write-Host (
                "[{0}] pid={1} remaining_sec={2} bytes={3} rows={4}" -f
                $RunType,
                $worker.Id,
                $remaining,
                [int64]$bytes,
                [int64]$rows
            )
            if ([DateTimeOffset]::Now -ge $deadline) {
                Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
                throw "Metadata collector exceeded MaxRuntimeSec=$MaxRuntimeSec."
            }
            Start-Sleep -Seconds 2
            $worker.Refresh()
        }

        Show-OwnedMetadataNewLogLines -Path $StdoutPath -Seen ([ref]$seenOut)
        Show-OwnedMetadataNewLogLines `
            -Path $StderrPath `
            -Seen ([ref]$seenErr) `
            -Color Red
        $exitCode = $worker.ExitCode
        if ($exitCode -ne 0) {
            throw "Metadata collector worker failed with exit code $exitCode."
        }
        if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
            throw "Metadata collector result was not created."
        }

        & $Python -u $ModulePath validate-result `
            --plan $PlanPath `
            --result $ResultPath |
            Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Final hash-bound result validation failed."
        }
        $result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
        if (
            $result.final -ne $true -or
            [string]$result.plan_hash -ne $ExpectedPlanHash -or
            [string]$result.artifact_hash -notmatch "^[0-9a-f]{64}$"
        ) {
            throw "Metadata collector result failed final/hash checks."
        }

        $launchRecord.status = "READY_FOR_POSTPROCESS"
        $launchRecord.final = $true
        $launchRecord.completed_at = [DateTimeOffset]::Now.ToString("o")
        $launchRecord.worker_exit_code = $exitCode
        $launchRecord.verdict = [string]$result.verdict
        $launchRecord.artifact_hash = [string]$result.artifact_hash
        $launchRecord.output_stats = @(
            Get-OwnedMetadataOutputStats -Paths $outputPaths
        )
        Write-OwnedMetadataJsonAtomic -Path $LaunchRecordPath -Value $launchRecord
        Update-OwnedMetadataRunState `
            -Status "READY_FOR_POSTPROCESS" `
            -Final $true `
            -Decision ([string]$result.verdict) `
            -NextStep ([string]$result.next_allowed_command)
        Write-Host "[$RunType] final verdict=$($result.verdict)" -ForegroundColor Green
        $exitCode = 0
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
        $launchRecord.output_stats = @(
            Get-OwnedMetadataOutputStats -Paths $outputPaths
        )
        Write-OwnedMetadataJsonAtomic -Path $LaunchRecordPath -Value $launchRecord
        if ($runStateOwned) {
            Update-OwnedMetadataRunState `
                -Status "STOPPED_INCOMPLETE" `
                -Final $false `
                -Errors 1 `
                -Decision "$($RunType.ToUpperInvariant())_STOPPED_INCOMPLETE" `
                -NextStep "Inspect logs, then visibly resume with the same immutable plan or reject the incomplete run." `
                -StopReason $message
        }
        Write-Host "[$RunType] STOPPED_INCOMPLETE: $message" -ForegroundColor Red
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
    return $exitCode
}
