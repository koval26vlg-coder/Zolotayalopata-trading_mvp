param(
    [string]$SourcePlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\plans\fast_first_funding_pressure_reversal_planonly_night_policy_20260714_121647.json",
    [string]$GoalPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\plans\2026-07-14-trading-mvp-current-goal.md",
    [string]$OutputPath = "",
    [int]$MaxRuntimeSec = 1200
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($MaxRuntimeSec -lt 1 -or $MaxRuntimeSec -gt 1200) {
    throw "MaxRuntimeSec must be between 1 and 1200 for Fast-First v5 PlanOnly."
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$GatePath = Join-Path $RepoRoot "docs\agent-log\active-run-gate.json"
$CurrentRunPath = Join-Path $RepoRoot "docs\agent-log\current-run.json"
$ArchiveDir = Join-Path $RepoRoot "docs\agent-log\archived-gates"
$GateCheck = Join-Path $RepoRoot "tools\check_active_run_gate.ps1"
$ModulePath = Join-Path $RepoRoot "trading_mvp\src\wick_rejection_reversal.py"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RunId = "fast_first_v5_wick_rejection_planonly_$Stamp"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\plans\fast_first_wick_rejection_reversal_planonly_$Stamp.json"
}

function Write-JsonAtomically {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $Parent = Split-Path -Parent $Path
    if ($Parent -and -not (Test-Path -LiteralPath $Parent)) {
        New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    }
    $Temporary = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
}

Write-Host "[1/4] Active-run gate" -ForegroundColor Cyan
$GateJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateCheck -GatePath $GatePath -Json
if ($LASTEXITCODE -ne 0) {
    throw "Active-run gate check failed with exit code $LASTEXITCODE."
}
$Gate = $GateJson | ConvertFrom-Json
Write-Host ("gate={0} run_id={1}" -f $Gate.status, $Gate.run_id)
if ($Gate.status -eq "RUNNING") {
    throw "Active-run gate is RUNNING. PlanOnly build is blocked."
}
if ($Gate.status -eq "STOPPED_INCOMPLETE") {
    throw "Active-run gate is STOPPED_INCOMPLETE. Resolve or reject it before PlanOnly."
}

foreach ($RequiredPath in @($SourcePlanPath, $GoalPath, $ModulePath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required file does not exist: $RequiredPath"
    }
}
if (Test-Path -LiteralPath $OutputPath) {
    throw "Refusing to overwrite immutable PlanOnly artifact: $OutputPath"
}

$Python = $null
foreach ($Candidate in @(
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
)) {
    if (-not $Python -and $Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        $Python = $Candidate
    }
}
if (-not $Python) {
    throw "Python runtime was not found."
}

$StartedAt = Get-Date
$Deadline = $StartedAt.AddSeconds($MaxRuntimeSec)
Write-Host "[2/4] Frozen inputs" -ForegroundColor Cyan
Write-Host "source_plan=$SourcePlanPath"
Write-Host "goal=$GoalPath"
Write-Host "output=$OutputPath"
Write-Host ("started={0:o} deadline={1:o} max_runtime_sec={2}" -f $StartedAt, $Deadline, $MaxRuntimeSec)

Write-Host "[3/4] Hash verification and v5 PlanOnly freeze" -ForegroundColor Cyan
& $Python $ModulePath build `
    --source-plan $SourcePlanPath `
    --goal $GoalPath `
    --output $OutputPath `
    --max-runtime-sec $MaxRuntimeSec
if ($LASTEXITCODE -ne 0) {
    throw "Fast-First v5 PlanOnly build failed with exit code $LASTEXITCODE."
}

Write-Host "[4/4] Independent persisted-artifact validation" -ForegroundColor Cyan
& $Python $ModulePath validate --plan $OutputPath
if ($LASTEXITCODE -ne 0) {
    throw "Fast-First v5 PlanOnly validation failed with exit code $LASTEXITCODE."
}

$Elapsed = [Math]::Round(((Get-Date) - $StartedAt).TotalSeconds, 3)
$ResolvedOutput = (Resolve-Path -LiteralPath $OutputPath).Path
$Plan = Get-Content -Raw -LiteralPath $ResolvedOutput | ConvertFrom-Json
$PlanFile = Get-Item -LiteralPath $ResolvedOutput
$PlanFileSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ResolvedOutput).Hash.ToLowerInvariant()
$FastEdgeRoot = Split-Path -Parent (Split-Path -Parent $ResolvedOutput)
$ManifestPath = Join-Path $FastEdgeRoot "manifests\$RunId.manifest.json"
$FinishedAt = Get-Date

$ManifestRecord = [ordered]@{
    schema = "fast_first_v5_planonly_manifest_v1"
    run_id = $RunId
    final = $true
    completed_cycles = 1
    cycles = 1
    remaining_cycles = 0
    rows = 1
    errors = 0
    output_path = $ResolvedOutput
    plan_path = $ResolvedOutput
    plan_hash = [string]$Plan.plan_hash
    plan_file_sha256 = $PlanFileSha256
    input_merkle_sha256 = [string]$Plan.sealed_input.input_merkle_sha256
    hypothesis_id = [string]$Plan.hypothesis.id
    plan_state = "PLAN_FROZEN_OOS_NOT_EVALUATED"
    started_at = $StartedAt.ToString("o")
    finished_at = $FinishedAt.ToString("o")
    actual_duration_sec = $Elapsed
    stop_reason = "completed_planonly_freeze"
}
Write-JsonAtomically -Value $ManifestRecord -Path $ManifestPath

New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
$PriorRunId = if ($Gate.run_id) { [string]$Gate.run_id } else { "unknown" }
$SafePriorRunId = $PriorRunId -replace '[^A-Za-z0-9._-]', '_'
$ArchiveStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$GateArchive = Join-Path $ArchiveDir "active-run-gate.$SafePriorRunId.superseded-by-v5-planonly.$ArchiveStamp.json"
$PointerArchive = Join-Path $ArchiveDir "current-run.$SafePriorRunId.superseded-by-v5-planonly.$ArchiveStamp.json"
if (Test-Path -LiteralPath $GatePath) {
    Copy-Item -LiteralPath $GatePath -Destination $GateArchive
}
if (Test-Path -LiteralPath $CurrentRunPath) {
    Copy-Item -LiteralPath $CurrentRunPath -Destination $PointerArchive
}

$LaunchRecordPath = Join-Path $RepoRoot "docs\agent-log\$RunId.launch.json"
$LaunchRecord = [ordered]@{
    schema = "fast_first_v5_planonly_record_v1"
    mode = "VISIBLE_BOUNDED_PLANONLY"
    run_id = $RunId
    visible_terminal_required = $true
    plan_path = $ResolvedOutput
    manifest_path = $ManifestPath
    plan_hash = [string]$Plan.plan_hash
    plan_file_sha256 = $PlanFileSha256
    input_merkle_sha256 = [string]$Plan.sealed_input.input_merkle_sha256
    started_at = $StartedAt.ToString("o")
    finished_at = $FinishedAt.ToString("o")
    actual_duration_sec = $Elapsed
    max_runtime_sec = $MaxRuntimeSec
    grid_search = $false
    evaluation = $false
    execution_probe = $false
    paper_forward = $false
    live_orders = $false
    api_keys = $false
    status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$GateCheck`" -Json"
}
Write-JsonAtomically -Value $LaunchRecord -Path $LaunchRecordPath

$GateRecord = [ordered]@{
    schema = "active_run_gate_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "READY_FOR_POSTPROCESS"
    gate_status = "READY_FOR_POSTPROCESS"
    final = $true
    primary_output_complete = $true
    expected_outputs_complete = $true
    replay_allowed = $false
    grid_allowed = $false
    backtest_allowed = $false
    evaluation_allowed = $false
    execution_probe_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    strategy_accepted = $false
    created_at = $StartedAt.ToString("o")
    updated_at = $FinishedAt.ToString("o")
    completed_cycles = 1
    total_cycles = 1
    remaining_cycles = 0
    rows = 1
    errors = 0
    monitor_pid = $null
    collector_pid = $null
    process_ids = $null
    output = [ordered]@{
        path = $ResolvedOutput
        type = "fast_first_v5_wick_rejection_reversal_planonly"
        bytes = $PlanFile.Length
    }
    output_path = $ResolvedOutput
    manifest_path = $ManifestPath
    launch_record_path = $LaunchRecordPath
    plan_path = $ResolvedOutput
    plan_hash = [string]$Plan.plan_hash
    plan_file_sha256 = $PlanFileSha256
    input_merkle_sha256 = [string]$Plan.sealed_input.input_merkle_sha256
    hypothesis_id = [string]$Plan.hypothesis.id
    plan_state = "PLAN_FROZEN_OOS_NOT_EVALUATED"
    purpose = "Freeze Fast-First v5 wick-rejection reversal before any train/OOS performance access."
    stop_reason = "completed_planonly_freeze"
    next_goal_decision = "FAST_FIRST_V5_PLAN_FROZEN"
    next_goal_reason = "Venue-local wick-rejection reversal contract, data seal, costs, split, folds and gates are frozen without OOS metrics."
    next_step_after_ready = "Implement and test the hash-bound no-grid v5 evaluator. Do not run OOS until evaluator readiness is validated."
    raw_gate_next_step_after_ready = "Implement and test the hash-bound no-grid v5 evaluator. Do not run OOS until evaluator readiness is validated."
    expected_outputs = [ordered]@{
        plan = $ResolvedOutput
        manifest = $ManifestPath
    }
    verification = [ordered]@{
        canonical_plan_hash_valid = $true
        plan_file_sha256 = $PlanFileSha256
        input_files_verified = [int]$Plan.sealed_input_verification.verified_source_files
        input_merkle_sha256 = [string]$Plan.sealed_input.input_merkle_sha256
        observed_oos_metrics_present = $false
        no_grid = $true
        setup_registry_state = [string]$Plan.setup_registry_state
    }
    superseded_gate_archive = $GateArchive
    superseded_pointer_archive = $PointerArchive
}
Write-JsonAtomically -Value $GateRecord -Path $GatePath

$PointerRecord = [ordered]@{
    schema = "active_run_pointer_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "READY_FOR_POSTPROCESS"
    gate_status = "READY_FOR_POSTPROCESS"
    final = $true
    primary_output_complete = $true
    expected_outputs_complete = $true
    updated_at = $FinishedAt.ToString("o")
    completed_cycles = 1
    total_cycles = 1
    remaining_cycles = 0
    rows = 1
    errors = 0
    output = $GateRecord.output
    manifest_path = $ManifestPath
    plan_path = $ResolvedOutput
    plan_hash = [string]$Plan.plan_hash
    plan_file_sha256 = $PlanFileSha256
    hypothesis_id = [string]$Plan.hypothesis.id
    collector_pid = $null
    monitor_pid = $null
    process_ids = $null
    launch_record_path = $LaunchRecordPath
    replay_allowed = $false
    grid_allowed = $false
    backtest_allowed = $false
    evaluation_allowed = $false
    execution_probe_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    strategy_accepted = $false
    plan_state = "PLAN_FROZEN_OOS_NOT_EVALUATED"
    next_goal_decision = "FAST_FIRST_V5_PLAN_FROZEN"
    next_goal_reason = $GateRecord.next_goal_reason
    next_step_after_ready = $GateRecord.next_step_after_ready
}
Write-JsonAtomically -Value $PointerRecord -Path $CurrentRunPath

Write-Host ("PLANONLY_COMPLETE elapsed_sec={0} output={1}" -f $Elapsed, $OutputPath) -ForegroundColor Green
