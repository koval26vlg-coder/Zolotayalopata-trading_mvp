param(
    [string]$InputPath = "",
    [string]$OutputPath = "",
    [int]$ProgressEveryRows = 1000000,
    [int]$MaxEvents = 1000,
    [int]$MaxRows = 0
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$normalizedDefault = Join-Path $repoRoot "exports\trading-mvp\normalized\ws_market_filtered_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.jsonl"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runId = "cross_venue_dislocation_full_$timestamp"
$manifestPath = Join-Path $runDir "$runId.manifest.json"
$consoleLogPath = Join-Path $runDir "$runId.console.log"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$agentLogPath = Join-Path $repoRoot "docs\agent-log\2026-07-08-trading-mvp-cross-venue-dislocation-full-scan.md"

if (-not $InputPath) {
    $InputPath = $normalizedDefault
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $backtestDir "cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"
}

New-Item -ItemType Directory -Force -Path $runDir, $backtestDir | Out-Null

function Set-JsonProperty($Object, [string]$Name, $Value) {
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Save-Json($Path, $Object) {
    $Object | ConvertTo-Json -Depth 100 | Set-Content -Path $Path -Encoding UTF8
}

function Read-JsonOrNew($Path) {
    if (Test-Path $Path) {
        return Get-Content -Raw -Path $Path | ConvertFrom-Json
    }
    return [pscustomobject]@{}
}

function Update-GateRunning() {
    $gate = Read-JsonOrNew $gatePath
    Set-JsonProperty $gate "schema" "active_run_gate_v1"
    Set-JsonProperty $gate "project" "trading_mvp"
    Set-JsonProperty $gate "status" "RUNNING"
    Set-JsonProperty $gate "run_id" $runId
    Set-JsonProperty $gate "purpose" "Visible full cross-venue MEXC/Gate spot dislocation scan; research-only; no grid/live/API keys/leverage/margin."
    Set-JsonProperty $gate "monitor_pid" $PID
    Set-JsonProperty $gate "process_ids" @($PID)
    Set-JsonProperty $gate "started_at" (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
    Set-JsonProperty $gate "output_path" $OutputPath
    Set-JsonProperty $gate "manifest_path" $manifestPath
    Set-JsonProperty $gate "state_path" $manifestPath
    Set-JsonProperty $gate "rows" 0
    Set-JsonProperty $gate "errors" 0
    Set-JsonProperty $gate "final" $false
    Set-JsonProperty $gate "expected_outputs" ([pscustomobject]@{ cross_venue_dislocation = $OutputPath })
    Set-JsonProperty $gate "next_goal_decision" "CROSS_VENUE_DISLOCATION_FULL_SCAN_RUNNING"
    Set-JsonProperty $gate "next_goal_reason" "Visible full scan is running. Do not start postprocess/grid/new collectors/live/API/paper-forward; only status checks are allowed."
    Set-JsonProperty $gate "next_step_after_ready" "Wait for the visible cross-venue full scan to finish, then inspect the output JSON and decide validation vs rejection."
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" "Wait for the visible cross-venue full scan to finish, then inspect the output JSON and decide validation vs rejection."
    Set-JsonProperty $gate "cross_venue_dislocation_full_scan_command" $CommandLine
    Save-Json $gatePath $gate
}

function Update-State($Status, $Final, $ExitCode, $Summary, $Decision, $NextDecision, $NextReason, $NextStep) {
    $now = Get-Date
    $duration = ($now - $script:startedAt).TotalSeconds
    $manifest = [pscustomobject]@{
        schema = "cross_venue_dislocation_full_scan_manifest_v1"
        project = "trading_mvp"
        run_id = $runId
        status = $Status
        final = $Final
        pid = $PID
        started_at = $script:startedAt.ToString("yyyy-MM-dd HH:mm:ss zzz")
        updated_at = $now.ToString("yyyy-MM-dd HH:mm:ss zzz")
        actual_duration_sec = [Math]::Round($duration, 1)
        input_path = $InputPath
        output_path = $OutputPath
        console_log_path = $consoleLogPath
        exit_code = $ExitCode
        summary = $Summary
        decision = $Decision
        command = $CommandLine
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
    }
    Save-Json $manifestPath $manifest

    $gate = Read-JsonOrNew $gatePath
    Set-JsonProperty $gate "status" $Status
    Set-JsonProperty $gate "run_id" $runId
    Set-JsonProperty $gate "monitor_pid" $PID
    Set-JsonProperty $gate "process_ids" @()
    Set-JsonProperty $gate "output_path" $OutputPath
    Set-JsonProperty $gate "manifest_path" $manifestPath
    Set-JsonProperty $gate "state_path" $manifestPath
    Set-JsonProperty $gate "final" $Final
    Set-JsonProperty $gate "actual_duration_sec" ([Math]::Round($duration, 1))
    $stopReason = if ($Final) {
        "completed"
    } elseif ($Status -eq "RUNNING") {
        "running"
    } else {
        "failed_or_interrupted"
    }
    Set-JsonProperty $gate "stop_reason" $stopReason
    Set-JsonProperty $gate "errors" $(if ($ExitCode -eq 0) { 0 } else { 1 })
    if ($Summary) {
        Set-JsonProperty $gate "rows" ([int64]$Summary.rows_read)
        Set-JsonProperty $gate "last_cross_venue_dislocation_full_output_path" $OutputPath
        Set-JsonProperty $gate "last_cross_venue_dislocation_full_rows_read" ([int64]$Summary.rows_read)
        Set-JsonProperty $gate "last_cross_venue_dislocation_full_candidate_events" ([int64]$Summary.candidate_events)
        Set-JsonProperty $gate "last_cross_venue_dislocation_full_eligible_events" ([int64]$Summary.eligible_events)
        Set-JsonProperty $gate "last_cross_venue_dislocation_full_max_gross_edge_bps" $Summary.max_gross_edge_bps
        Set-JsonProperty $gate "last_cross_venue_dislocation_full_max_net_edge_bps" $Summary.max_net_edge_bps
    }
    Set-JsonProperty $gate "next_goal_decision" $NextDecision
    Set-JsonProperty $gate "next_goal_reason" $NextReason
    Set-JsonProperty $gate "next_step_after_ready" $NextStep
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" $NextStep
    Save-Json $gatePath $gate
}

$script:startedAt = Get-Date
$CommandLine = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\trading_mvp\run_mvp.ps1`" -Action cross-venue-dislocation -InputPath `"$InputPath`" -OutputPath `"$OutputPath`" -CrossVenueProgressEveryRows $ProgressEveryRows -CrossVenueMaxEvents $MaxEvents"
if ($MaxRows -gt 0) {
    $CommandLine += " -CrossVenueMaxRows $MaxRows"
}

if (-not (Test-Path $InputPath)) {
    throw "InputPath not found: $InputPath"
}

Update-GateRunning
Update-State "RUNNING" $false 0 $null $null "CROSS_VENUE_DISLOCATION_FULL_SCAN_RUNNING" "Visible full scan is running." "Wait for scan completion; only status checks are allowed."

Start-Transcript -Path $consoleLogPath -Force | Out-Null
try {
    Write-Host "Starting visible cross-venue full scan"
    Write-Host "Input:  $InputPath"
    Write-Host "Output: $OutputPath"
    Write-Host "Progress every rows: $ProgressEveryRows"
    Write-Host "Command: $CommandLine"
    Write-Host ""

    & (Join-Path $repoRoot "trading_mvp\run_mvp.ps1") `
        -Action cross-venue-dislocation `
        -InputPath $InputPath `
        -OutputPath $OutputPath `
        -CrossVenueProgressEveryRows $ProgressEveryRows `
        -CrossVenueMaxEvents $MaxEvents `
        -CrossVenueMaxRows $MaxRows

    $exitCode = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } else { 0 }
    if ($exitCode -ne 0) {
        throw "cross-venue full scan exited with code $exitCode"
    }
    if (-not (Test-Path $OutputPath)) {
        throw "scan completed without output artifact: $OutputPath"
    }

    $result = Get-Content -Raw -Path $OutputPath | ConvertFrom-Json
    $summary = $result.summary
    $eligible = [int64]$summary.eligible_events
    $scanComplete = [bool]$summary.scan_complete
    $decision = [string]$result.decision

    if ($eligible -gt 0 -and $scanComplete) {
        $nextDecision = "CROSS_VENUE_DISLOCATION_FULL_SCAN_CANDIDATES_NEED_VALIDATION"
        $nextReason = "Full scan found net-positive cross-venue candidates after base-tier costs; next step is OOS/walk-forward/stress/economics validation, not live/grid."
        $nextStep = "Build and run cross-venue OOS/walk-forward/stress/economics validation on the full-scan artifact. Do not start collect/grid/live/API/paper-forward."
    } elseif ($scanComplete) {
        $nextDecision = "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH"
        $nextReason = "Full scan found no eligible net-positive cross-venue dislocation events after base-tier fees/slippage/rebalance buffer."
        $nextStep = "Reject or park cross-venue spot dislocation under current base-fee assumptions, then select the next non-HFT structural branch PlanOnly. Do not grid-tune this rejected branch."
    } else {
        $nextDecision = "CROSS_VENUE_DISLOCATION_FULL_SCAN_TRUNCATED"
        $nextReason = "Full scan output is truncated; rerun visibly without MaxRows before deciding."
        $nextStep = "Rerun visible full cross-venue scan without MaxRows. Do not interpret truncated output as rejection or acceptance."
    }

    Update-State "READY_FOR_POSTPROCESS" $true $exitCode $summary $decision $nextDecision $nextReason $nextStep

    @"
# trading_mvp cross-venue dislocation full scan

Agent: Codex visible wrapper
Time: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")

Input:
- $InputPath

Output:
- $OutputPath

Manifest:
- $manifestPath

Summary:
- rows_read: $($summary.rows_read)
- bbo_rows: $($summary.bbo_rows)
- matched_bases: $($summary.matched_bases)
- candidate_events: $($summary.candidate_events)
- eligible_events: $($summary.eligible_events)
- max_gross_edge_bps: $($summary.max_gross_edge_bps)
- max_net_edge_bps: $($summary.max_net_edge_bps)
- scan_complete: $($summary.scan_complete)
- decision: $decision

Next:
- $nextStep

Constraints:
- research-only
- no live orders
- no API keys
- no leverage/margin
- no grid before validation gate
"@ | Set-Content -Path $agentLogPath -Encoding UTF8

    Write-Host ""
    Write-Host "Full scan completed."
    Write-Host "Decision: $decision"
    Write-Host "Next: $nextStep"
} catch {
    $message = $_.Exception.Message
    Write-Host ""
    Write-Host "Full scan failed: $message" -ForegroundColor Red
    Update-State "STOPPED_INCOMPLETE" $false 1 $null $null "CROSS_VENUE_DISLOCATION_FULL_SCAN_STOPPED_INCOMPLETE" $message "Inspect console log and rerun the visible full scan; do not continue validation from incomplete output."
    throw
} finally {
    Stop-Transcript | Out-Null
}

Write-Host ""
Read-Host "Press Enter to close this visible scan window"
