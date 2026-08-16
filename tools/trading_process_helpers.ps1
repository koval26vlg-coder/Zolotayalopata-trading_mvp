# Trading Process Launcher & Timeout Recovery Helpers
# Extracted from trading_mvp/run_mvp.ps1 for modular reuse

function Set-RunTimedOutIncompleteHelper {
    param(
        [string]$TimedOutAction,
        [int]$MaxRuntimeSecVal = $MaxRuntimeSec,
        [string]$CustomGatePath = $ActiveRunGatePath
    )

    if ($CustomGatePath) {
        $resolvedGatePath = [System.IO.Path]::GetFullPath($CustomGatePath)
        $agentLogDir = Split-Path -Parent $resolvedGatePath
        $paths = @($resolvedGatePath, (Join-Path $agentLogDir "current-run.json"))
    } else {
        $agentLogDir = Join-Path $ProjectRoot "docs\agent-log"
        $paths = @(
            (Join-Path $agentLogDir "active-run-gate.json"),
            (Join-Path $agentLogDir "current-run.json")
        )
    }
    $now = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffffffK")
    foreach ($path in $paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            $document = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
            foreach ($entry in @(
                @("status", "STOPPED_INCOMPLETE"),
                @("updated_at", $now),
                @("collector_pid", $null),
                @("monitor_pid", $null),
                @("process_ids", @()),
                @("stop_reason", "MAX_RUNTIME_SEC_EXCEEDED"),
                @("failure", "Action '$TimedOutAction' exceeded MaxRuntimeSec=$MaxRuntimeSecVal")
            )) {
                if ($document.PSObject.Properties.Name -contains $entry[0]) {
                    $document.($entry[0]) = $entry[1]
                } else {
                    $document | Add-Member -NotePropertyName $entry[0] -NotePropertyValue $entry[1]
                }
            }
            if ([string]$document.schema -eq "active_run_gate_v2") {
                foreach ($entry in @(
                    @("gate_status", "STOPPED_INCOMPLETE"),
                    @("final", $false),
                    @("replay_allowed", $false),
                    @("grid_allowed", $false),
                    @("backtest_allowed", $false),
                    @("paper_forward_allowed", $false),
                    @("next_goal_decision", "FAST_FIRST_MAX_RUNTIME_EXCEEDED")
                )) {
                    if ($document.PSObject.Properties.Name -contains $entry[0]) {
                        $document.($entry[0]) = $entry[1]
                    } else {
                        $document | Add-Member -NotePropertyName $entry[0] -NotePropertyValue $entry[1]
                    }
                }
            }
            $temp = "$path.tmp.$PID"
            $document | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding utf8
            Move-Item -LiteralPath $temp -Destination $path -Force
        } catch {
            Write-Warning "Could not mark timed-out run incomplete at ${path}: $($_.Exception.Message)"
        }
    }
}

function Invoke-TradingMvpCli {
    param(
        [object[]]$ArgsList,
        [string]$ScriptPath = $cli,
        [int]$MaxRuntimeSecVal = $MaxRuntimeSec
    )

    if ($MaxRuntimeSecVal -lt 1 -or $MaxRuntimeSecVal -gt 10800) {
        throw "MaxRuntimeSec must be in [1, 10800]."
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $python
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $false
    $startInfo.RedirectStandardError = $false
    $startInfo.WorkingDirectory = $ProjectRoot
    $startInfo.ArgumentList.Add($ScriptPath)
    foreach ($argument in $ArgsList) {
        $startInfo.ArgumentList.Add([string]$argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Failed to start Python process: $ScriptPath"
    }
    if (-not $process.WaitForExit($MaxRuntimeSecVal * 1000)) {
        try { $process.Kill($true) } catch { }
        try { $process.WaitForExit(5000) } catch { }
        Set-RunTimedOutIncomplete -TimedOutAction $Action -MaxRuntimeSecVal $MaxRuntimeSecVal
        throw "Process exceeded MaxRuntimeSec=$MaxRuntimeSecVal and was terminated: $ScriptPath"
    }
    if ($process.ExitCode -ne 0) {
        exit $process.ExitCode
    }
}

function New-BasisCodeSnapshot {
    $sourceDir = Join-Path $PSScriptRoot "..\trading_mvp\src"
    if (-not (Test-Path $sourceDir)) {
        $sourceDir = Join-Path $ProjectRoot "trading_mvp\src"
    }
    $raw = & $python $historicalBasisCodeSnapshotCli --source-dir $sourceDir --output-root $BasisCodeSnapshotRoot
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Failed to create historical basis code snapshot."
    }
    $snapshot = ($raw | Out-String | ConvertFrom-Json)
    if (-not $snapshot.code_snapshot_hash -or -not (Test-Path -LiteralPath $snapshot.manifest_path)) {
        throw "Historical basis code snapshot is invalid."
    }
    Write-Host "CODE_SNAPSHOT hash=$($snapshot.code_snapshot_hash) files=$($snapshot.file_count) cache_hit=$($snapshot.cache_hit) path=$($snapshot.snapshot_path)"
    return $snapshot
}
