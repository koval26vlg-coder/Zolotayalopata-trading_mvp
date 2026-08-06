param(
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [int]$IntervalSec = 60,
    [int]$MaxIterations = 0,
    [switch]$Once,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"

function Invoke-GateStatus {
    param([string]$Path)

    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -GatePath $Path -Json | ConvertFrom-Json
    $output = $gate.output
    $lastWriteAge = if ($null -ne $output -and $null -ne $output.last_write_age_sec) { $output.last_write_age_sec } else { $null }
    $outputLines = if ($null -ne $output -and $null -ne $output.line_count) { $output.line_count } else { $null }
    $outputFiles = if ($null -ne $output -and $null -ne $output.file_count) { $output.file_count } else { $null }

    $nextAction = "inspect_gate"
    if ([string]$gate.status -eq "RUNNING") {
        $nextAction = "wait_status_only"
    } elseif ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
        $nextAction = "visible_resume_or_reject_incomplete_dataset"
    } elseif ([string]$gate.status -eq "READY_FOR_POSTPROCESS" -and $null -ne $gate.replay_allowed -and -not [bool]$gate.replay_allowed) {
        $nextAction = "do_not_replay_rejected_artifact_start_new_visible_collect_after_explicit_approval"
    } elseif ([string]$gate.status -eq "READY_FOR_POSTPROCESS") {
        $nextAction = "run_next_guarded_postprocess_or_validation_step"
    }

    return [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_active_run_monitor"
        read_only = $true
        would_start = $false
        status = [string]$gate.status
        gate_status = [string]$gate.gate_status
        warning = [string]$gate.warning
        run_id = [string]$gate.run_id
        completed_cycles = $gate.completed_cycles
        total_cycles = $gate.total_cycles
        remaining_cycles = $gate.remaining_cycles
        remaining_hours = $gate.remaining_hours
        estimated_finish = $gate.estimated_finish
        final = $gate.final
        rows = $gate.rows
        errors = $gate.errors
        monitor_pid = $gate.monitor_pid
        monitor_pid_alive = $gate.monitor_pid_alive
        live_process_ids = @($gate.live_process_ids)
        output_path = if ($null -ne $output) { [string]$output.path } else { $null }
        output_kind = if ($null -ne $output) { [string]$output.kind } else { $null }
        output_line_count = $outputLines
        output_file_count = $outputFiles
        output_last_write_age_sec = $lastWriteAge
        manifest_path = [string]$gate.manifest_path
        stop_reason = [string]$gate.stop_reason
        next_action = $nextAction
        next_goal_decision = [string]$gate.next_goal_decision
        replay_allowed = $gate.replay_allowed
        blocked_actions = @(
            "postprocess_while_running",
            "replay_or_grid_while_running",
            "new_collector_while_running",
            "hidden_background_start",
            "live_orders",
            "api_keys",
            "leverage_or_margin"
        )
    }
}

function Write-MonitorLine {
    param([object]$Status)

    $parts = @(
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),
        "status=$($Status.status)",
        "run=$($Status.run_id)",
        "cycles=$($Status.completed_cycles)/$($Status.total_cycles)",
        "rows=$($Status.rows)",
        "errors=$($Status.errors)"
    )
    if ($null -ne $Status.remaining_hours) {
        $parts += "remaining_h=$($Status.remaining_hours)"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Status.estimated_finish)) {
        $parts += "eta=$($Status.estimated_finish)"
    }
    if ($null -ne $Status.output_last_write_age_sec) {
        $parts += "last_write_age_s=$($Status.output_last_write_age_sec)"
    }
    $parts += "next=$($Status.next_action)"
    Write-Host ($parts -join " | ")
}

if ($IntervalSec -lt 5) {
    $IntervalSec = 5
}

if ($Once -or $Json) {
    $status = Invoke-GateStatus -Path $GatePath
    if ($Json) {
        $status | ConvertTo-Json -Depth 8
    } else {
        Write-MonitorLine -Status ([pscustomobject]$status)
        Write-Host "Read-only monitor: no collector/replay/grid/postprocess was started."
    }
    exit 0
}

Write-Host "trading_mvp active-run monitor (read-only)" -ForegroundColor Cyan
Write-Host "Gate: $GatePath"
Write-Host "Interval: $IntervalSec sec"
Write-Host "No collector/replay/grid/postprocess will be started by this monitor."
Write-Host ""

$iteration = 0
while ($true) {
    $iteration += 1
    try {
        $status = [pscustomobject](Invoke-GateStatus -Path $GatePath)
        Write-MonitorLine -Status $status
        if ($status.status -ne "RUNNING") {
            Write-Host "Monitor stopping because gate status is $($status.status)." -ForegroundColor Yellow
            break
        }
    } catch {
        Write-Host ("[{0}] monitor read error: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message) -ForegroundColor Red
    }

    if ($MaxIterations -gt 0 -and $iteration -ge $MaxIterations) {
        Write-Host "Monitor stopping after MaxIterations=$MaxIterations."
        break
    }
    Start-Sleep -Seconds $IntervalSec
}
