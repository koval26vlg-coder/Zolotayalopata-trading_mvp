param(
    [switch]$Json,
    [switch]$PlanOnly,
    [ValidateSet("all", "fast", "core", "integration", "slow")]
    [string]$Shard = "all",
    [ValidateRange(1, 86400)]
    [int]$TimeoutSec = 1800,
    [string]$TestPath = "trading_mvp/tests",
    [string]$Pattern = "test_*.py",
    [string]$StartDirectory = "",
    [string[]]$PythonCandidates = @()
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($StartDirectory)) {
    $StartDirectory = Join-Path $repoRoot $TestPath
} elseif (-not [System.IO.Path]::IsPathRooted($StartDirectory)) {
    $StartDirectory = Join-Path $repoRoot $StartDirectory
}
$StartDirectory = [System.IO.Path]::GetFullPath($StartDirectory)

function Add-Candidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$Path
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    if (-not $Candidates.Contains($Path)) {
        $Candidates.Add($Path) | Out-Null
    }
}

function Test-PythonCandidate {
    param([string]$PythonPath)
    $result = [ordered]@{
        path = $PythonPath
        exists = $false
        executable = ""
        has_requests = $false
        requests_version = ""
        error = ""
    }

    try {
        $command = Get-Command $PythonPath -ErrorAction SilentlyContinue
        $resolvedPath = if ($command) { $command.Source } else { $PythonPath }
        $result.executable = $resolvedPath
        $result.exists = [bool](Test-Path -LiteralPath $resolvedPath)
        if (-not $result.exists) {
            $result.error = "not found"
            return [pscustomobject]$result
        }

        $probe = & $resolvedPath -c "import requests, sys; print(sys.executable); print(requests.__version__)" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $result.error = ($probe | Out-String).Trim()
            return [pscustomobject]$result
        }
        $lines = @($probe | ForEach-Object { [string]$_ })
        $result.has_requests = $true
        if ($lines.Count -ge 1) {
            $result.executable = $lines[0]
        }
        if ($lines.Count -ge 2) {
            $result.requests_version = $lines[1]
        }
    } catch {
        $result.error = $_.Exception.Message
    }
    return [pscustomobject]$result
}

function Get-TestFileShard {
    param([string]$Name)

    $slowFiles = @(
        "test_basis.py",
        "test_visible_ws_collect_wrapper.py"
    )
    $fastFiles = @(
        "test_active_run_gate.py",
        "test_cli_ws_input_guard.py",
        "test_cross_sectional_capitulation.py",
        "test_cross_venue_full_scan_audit.py",
        "test_cross_venue_lead_lag.py",
        "test_event_labeler.py",
        "test_event_slicer.py",
        "test_event_validation.py",
        "test_execution_gate.py",
        "test_experiments.py",
        "test_funding.py",
        "test_funding_pairs.py",
        "test_pit_universe_public_probe.py",
        "test_pit_universe_clean_slice_spec.py",
        "test_pit_cross_venue_screen.py",
        "test_pit_cross_venue_diagnostic_freeze.py",
        "test_pit_cross_venue_evidence_gap.py",
        "test_pit_cross_venue_fast_pipeline.py",
        "test_pit_cross_venue_availability.py",
        "test_pit_cross_venue_forward_collector.py",
        "test_pit_cross_venue_forward_plan.py",
        "test_pit_cross_venue_forward_probe.py",
        "test_pit_cross_venue_short_probe_collector.py",
        "test_pit_cross_venue_short_probe_plan.py",
        "test_pit_universe_snapshot_collector.py",
        "test_pit_universe_snapshot_quality.py",
        "test_hypothesis_contract.py",
        "test_night_schedule_plan.py",
        "test_night_schedule_approval.py",
        "test_night_schedule_status.py",
        "test_night_schedule_quality.py",
        "test_powershell_tooling.py",
        "test_risk.py",
        "test_spot_pit_event_collector.py",
        "test_spot_pit_event_analyzer.py",
        "test_spot_pit_event_public_preflight.py",
        "test_spot_pit_event_readiness.py",
        "test_universe.py",
        "test_ws_collector.py",
        "test_ws_normalizer.py"
    )
    $coreFiles = @(
        "test_backtester.py",
        "test_cross_venue_dislocation.py",
        "test_listing_calendar.py",
        "test_listing_event_normalizer.py",
        "test_listing_event_replay.py",
        "test_momentum_backtest.py",
        "test_momentum_survivorship_audit.py",
        "test_multi_bot.py",
        "test_perp_replay.py",
        "test_perp_report.py",
        "test_slow_liquidity_event_census.py",
        "test_slow_liquidity_feature_normalizer.py",
        "test_slow_liquidity_fixed_signal_plan.py",
        "test_slow_liquidity_replay_v1.py",
        "test_spot_perp_basis_mean_reversion.py",
        "test_ws_grid_search.py",
        "test_ws_replay.py"
    )

    if ($slowFiles -contains $Name) { return "slow" }
    if ($fastFiles -contains $Name) { return "fast" }
    if ($coreFiles -contains $Name) { return "core" }
    return "integration"
}

# The legacy runner used one unbounded `unittest discover` process. Explicit
# file lists keep discovery deterministic while allowing per-shard timeouts.
function Convert-ToCommandText {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    $quoted = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }
    return '"' + $Executable + '" ' + ($quoted -join " ")
}

function Invoke-TestShard {
    param(
        [string]$Executable,
        [string]$ShardName,
        [string[]]$Arguments,
        [int]$ProcessTimeoutSec,
        [bool]$CaptureOutput
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $false
    $startInfo.RedirectStandardOutput = $CaptureOutput
    $startInfo.RedirectStandardError = $CaptureOutput
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Failed to start test shard $ShardName"
    }

    $stdoutTask = if ($CaptureOutput) { $process.StandardOutput.ReadToEndAsync() } else { $null }
    $stderrTask = if ($CaptureOutput) { $process.StandardError.ReadToEndAsync() } else { $null }
    $completed = $process.WaitForExit($ProcessTimeoutSec * 1000)
    if (-not $completed) {
        try {
            $process.Kill($true)
            $process.WaitForExit()
        } catch {
            Write-Warning "Failed to kill timed-out shard ${ShardName}: $($_.Exception.Message)"
        }
    }

    $stdout = if ($CaptureOutput) { $stdoutTask.GetAwaiter().GetResult() } else { "" }
    $stderr = if ($CaptureOutput) { $stderrTask.GetAwaiter().GetResult() } else { "" }
    $exitCode = if ($completed) { $process.ExitCode } else { 124 }
    $process.Dispose()

    return [pscustomobject][ordered]@{
        shard = $ShardName
        status = if (-not $completed) { "TIMED_OUT" } elseif ($exitCode -eq 0) { "PASSED" } else { "FAILED" }
        exit_code = $exitCode
        timed_out = (-not $completed)
        timeout_sec = $ProcessTimeoutSec
        stdout = $stdout
        stderr = $stderr
    }
}

$candidateList = [System.Collections.Generic.List[string]]::new()
foreach ($candidate in $PythonCandidates) {
    Add-Candidate -Candidates $candidateList -Path $candidate
}
Add-Candidate -Candidates $candidateList -Path $env:TRADING_MVP_PYTHON
Add-Candidate -Candidates $candidateList -Path "C:\Program Files\Python313\python.exe"
Add-Candidate -Candidates $candidateList -Path "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe"
Add-Candidate -Candidates $candidateList -Path "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) {
    Add-Candidate -Candidates $candidateList -Path $pythonCommand.Source
}

$candidateResults = @($candidateList | ForEach-Object { Test-PythonCandidate -PythonPath $_ })
$selected = $candidateResults | Where-Object { $_.has_requests } | Select-Object -First 1

if (-not (Test-Path -LiteralPath $StartDirectory -PathType Container)) {
    throw "Test start directory does not exist: $StartDirectory"
}

$allTestFiles = @(Get-ChildItem -LiteralPath $StartDirectory -Filter $Pattern -File | Sort-Object Name)
$requestedShards = if ($Shard -eq "all") { @("fast", "core", "integration", "slow") } else { @($Shard) }
$shardPlans = @()
foreach ($shardName in $requestedShards) {
    $files = @($allTestFiles | Where-Object { (Get-TestFileShard -Name $_.Name) -eq $shardName })
    if ($files.Count -eq 0) {
        continue
    }
    $relativeFiles = @($files | ForEach-Object {
        [System.IO.Path]::GetRelativePath($repoRoot, $_.FullName).Replace('\', '/')
    })
    $arguments = @("-m", "unittest") + $relativeFiles
    $commandText = if ($selected) {
        Convert-ToCommandText -Executable ([string]$selected.executable) -Arguments $arguments
    } else {
        ""
    }
    $shardPlans += [pscustomobject][ordered]@{
        shard = $shardName
        test_files = $relativeFiles
        arguments = $arguments
        command = $commandText
    }
}

$commands = @($shardPlans | ForEach-Object { $_.command })
$testFiles = @($shardPlans | ForEach-Object { $_.test_files } | ForEach-Object { $_ })
$baseResult = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "run_trading_tests"
    plan_only = [bool]$PlanOnly
    ok = [bool]$selected -and ($shardPlans.Count -gt 0)
    status = if (-not $selected) { "NO_PYTHON_WITH_REQUESTS" } elseif ($shardPlans.Count -eq 0) { "NO_TESTS" } else { "READY" }
    selected_python = if ($selected) { [string]$selected.executable } else { "" }
    requests_version = if ($selected) { [string]$selected.requests_version } else { "" }
    shard = $Shard
    shards = @($requestedShards)
    timeout_sec = $TimeoutSec
    command = if ($commands.Count -eq 1) { $commands[0] } else { $commands -join "; " }
    commands = $commands
    test_files = $testFiles
    start_directory = $StartDirectory
    pattern = $Pattern
    candidates = @($candidateResults)
}

if ($PlanOnly) {
    if ($Json) {
        $baseResult | ConvertTo-Json -Depth 10
    } else {
        Write-Host "trading_mvp test runner plan" -ForegroundColor Cyan
        Write-Host "Status: $($baseResult.status)"
        Write-Host "Selected Python: $($baseResult.selected_python)"
        Write-Host "requests: $($baseResult.requests_version)"
        Write-Host "Shard: $Shard; timeout: $TimeoutSec sec"
        foreach ($plan in $shardPlans) {
            Write-Host "[$($plan.shard)] $($plan.test_files.Count) files"
            Write-Host $plan.command
        }
    }
    if ($baseResult.ok) { exit 0 } else { exit 2 }
}

if (-not $selected -or $shardPlans.Count -eq 0) {
    if ($Json) {
        $baseResult | ConvertTo-Json -Depth 10
    } else {
        Write-Error "Test runner is not ready: $($baseResult.status)"
    }
    exit 2
}

if (-not $Json) {
    Write-Host "trading_mvp test runner" -ForegroundColor Cyan
    Write-Host "Selected Python: $($selected.executable)"
    Write-Host "requests: $($selected.requests_version)"
    Write-Host "Shard: $Shard; timeout per shard: $TimeoutSec sec"
}

$shardResults = @()
foreach ($plan in $shardPlans) {
    if (-not $Json) {
        Write-Host ""
        Write-Host "[$($plan.shard)] $($plan.test_files.Count) files" -ForegroundColor Cyan
        Write-Host $plan.command
    }
    $shardResult = Invoke-TestShard `
        -Executable ([string]$selected.executable) `
        -ShardName ([string]$plan.shard) `
        -Arguments ([string[]]$plan.arguments) `
        -ProcessTimeoutSec $TimeoutSec `
        -CaptureOutput ([bool]$Json)
    $shardResults += $shardResult
    if ($shardResult.exit_code -ne 0) {
        break
    }
}

$failed = @($shardResults | Where-Object { $_.exit_code -ne 0 })
$exitCode = if ($failed.Count -gt 0) { [int]$failed[0].exit_code } else { 0 }
$result = [ordered]@{}
foreach ($entry in $baseResult.GetEnumerator()) {
    $result[$entry.Key] = $entry.Value
}
$result.plan_only = $false
$result.ok = ($exitCode -eq 0)
$result.status = if ($exitCode -eq 0) { "PASSED" } elseif ($exitCode -eq 124) { "TIMED_OUT" } else { "FAILED" }
$result.exit_code = $exitCode
$result.shard_results = @($shardResults)

if ($Json) {
    $result | ConvertTo-Json -Depth 12
}
exit $exitCode
