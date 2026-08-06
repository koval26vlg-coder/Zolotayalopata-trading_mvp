param(
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_sectional_capitulation_planonly_20260712_2125.json",
    [string]$ExpectedPlanSha256 = "c24edb25d8690c0c68d68fd58629cb62b760814b98d0d70c74a22848bdb633fb",
    [string]$OutputPath = "",
    [string]$RunId = "",
    [switch]$PlanOnly,
    [switch]$ConfirmedResearchReplay,
    [switch]$VisibleChild,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$modulePath = Join-Path $repoRoot "trading_mvp\src\cross_sectional_capitulation.py"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $RunId) { $RunId = "cross_sectional_capitulation_fixed_$stamp" }
if (-not $OutputPath) { $OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\backtests\$RunId.json" }
$runRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\run"
$manifestPath = Join-Path $runRoot "$RunId.manifest.json"
$consoleLogPath = Join-Path $runRoot "$RunId.console.log"

function Write-JsonAtomic {
    param($Value, [string]$Path)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temp = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw "Plan not found: $PlanPath" }
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "Replay module not found: $modulePath" }
$planHash = (Get-FileHash -LiteralPath $PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($planHash -ne $ExpectedPlanSha256.ToLowerInvariant()) { throw "Sealed plan hash mismatch: expected=$ExpectedPlanSha256 observed=$planHash" }
$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
if ([string]$plan.schema -ne "cross_sectional_capitulation_plan_v1" -or -not [bool]$plan.fixed_parameters_no_grid -or -not [bool]$plan.research_only) {
    throw "Invalid fixed research plan contract."
}

$command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanSha256 $ExpectedPlanSha256 -OutputPath `"$OutputPath`" -RunId $RunId -ConfirmedResearchReplay -VisibleChild"
$preview = [ordered]@{
    schema = "cross_sectional_capitulation_visible_plan_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    would_start = [bool]($ConfirmedResearchReplay -and -not $PlanOnly)
    would_open_visible_terminal = [bool]($ConfirmedResearchReplay -and -not $PlanOnly -and -not $VisibleChild)
    research_only = $true
    fixed_parameters_no_grid = $true
    run_id = $RunId
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_path = $OutputPath
    manifest_path = $manifestPath
    console_log_path = $consoleLogPath
    collect = $false
    grid_search = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    command = $command
}
if ($PlanOnly -or -not $ConfirmedResearchReplay) {
    if ($Json) { $preview | ConvertTo-Json -Depth 20 } else { $preview | Format-List }
    exit 0
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -eq "RUNNING") { throw "Active run gate is RUNNING for $($gate.run_id)." }

if (-not $VisibleChild) {
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $args = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanSha256", $ExpectedPlanSha256,
        "-OutputPath", $OutputPath,
        "-RunId", $RunId,
        "-ConfirmedResearchReplay", "-VisibleChild"
    )
    $terminal = Start-Process -FilePath $pwsh -ArgumentList $args -WindowStyle Normal -PassThru
    $preview.mode = "cross_sectional_capitulation_visible_terminal_launched"
    $preview.visible_terminal_pid = $terminal.Id
    if ($Json) { $preview | ConvertTo-Json -Depth 20 } else {
        Write-Host "Visible fixed replay launched." -ForegroundColor Cyan
        Write-Host "PID: $($terminal.Id)"
        Write-Host "RunId: $RunId"
    }
    exit 0
}

$host.UI.RawUI.WindowTitle = "trading_mvp cross-sectional capitulation - $RunId"
New-Item -ItemType Directory -Force -Path $runRoot, (Split-Path -Parent $OutputPath) | Out-Null
$python = "C:\Program Files\Python313\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python not found: $python" }
$startedAt = Get-Date
$estimatedFinish = $startedAt.AddMinutes(2)
$manifest = [ordered]@{
    schema = "cross_sectional_capitulation_manifest_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    final = $false
    stop_reason = $null
    started_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    requested_duration_sec = 120
    estimated_finish = $estimatedFinish.ToString("yyyy-MM-ddTHH:mm:sszzz")
    monitor_pid = $PID
    process_ids = @($PID)
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_path = $OutputPath
    console_log_path = $consoleLogPath
    rows = 0
    errors = 0
    research_only = $true
    collect = $false
    grid_search = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    command = $command
}
Write-JsonAtomic $manifest $manifestPath

$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
foreach ($pair in @(
    @("status", "RUNNING"), @("gate_status", "RUNNING"), @("run_id", $RunId),
    @("purpose", "Visible fixed 4h cross-sectional capitulation replay on existing Gate spot history; no collect/grid/live/API."),
    @("updated_at", $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")), @("started_at", $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")),
    @("monitor_pid", $PID), @("collector_pid", $null), @("process_ids", @($PID)),
    @("manifest_path", $manifestPath), @("output_path", $OutputPath), @("output_kind", "file"),
    @("final", $false), @("expected_outputs_complete", $false), @("rows", 0), @("errors", 0),
    @("requested_duration_sec", 120), @("estimated_finish", $estimatedFinish.ToString("yyyy-MM-ddTHH:mm:sszzz")),
    @("next_goal_decision", "CROSS_SECTIONAL_CAPITULATION_FIXED_REPLAY_RUNNING"),
    @("next_goal_reason", "Visible fixed replay is running; only status checks are allowed."),
    @("next_step_after_ready", "Inspect OOS/walk-forward/stress/economics gates; do not tune the sample."),
    @("replay_allowed", $false), @("grid_allowed", $false), @("paper_forward_allowed", $false),
    @("live_orders", $false), @("api_keys", $false), @("leverage_or_margin", $false)
)) { Set-JsonProperty $gateDoc $pair[0] $pair[1] }
Set-JsonProperty $gateDoc "raw_gate_next_step_after_ready" $gateDoc.next_step_after_ready
Set-JsonProperty $gateDoc "output" ([ordered]@{ path = $OutputPath; kind = "file" })
Set-JsonProperty $gateDoc "expected_outputs" ([ordered]@{ replay_report = $OutputPath })
Write-JsonAtomic $gateDoc $gatePath

$pointer = [ordered]@{
    schema = "active_run_pointer_v1"; project = "trading_mvp"; run_id = $RunId; status = "RUNNING"
    updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); manifest_path = $manifestPath
    output = [ordered]@{ path = $OutputPath; kind = "file" }; collector_pid = $null; monitor_pid = $PID
    process_ids = @($PID); branch = "cross_sectional_capitulation_rebound_4h_spot"; strategy_accepted = $false
    expected_outputs = [ordered]@{ replay_report = $OutputPath }; expected_outputs_complete = $false
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "Cross-Sectional Capitulation Fixed Replay" -ForegroundColor Cyan
Write-Host "RunId: $RunId"
Write-Host "Plan SHA256: $planHash"
Write-Host "Output: $OutputPath"
Write-Host "Scope: existing Gate spot 4h history; no collect/grid/live/API/margin" -ForegroundColor Yellow

$exitCode = 1
try {
    & $python $modulePath --plan $PlanPath --expected-plan-sha256 $ExpectedPlanSha256 --output $OutputPath 2>&1 | Tee-Object -FilePath $consoleLogPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Replay exited with code $exitCode" }
    $report = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    $finishedAt = Get-Date
    $nextDecision = if ([bool]$report.research_candidate) {
        "CROSS_SECTIONAL_CAPITULATION_CANDIDATE_REQUIRES_INDEPENDENT_AUDIT_PLANONLY"
    } else { [string]$report.decision }
    $nextStep = if ([bool]$report.research_candidate) {
        "Run a fail-closed independent artifact audit PlanOnly; paper-forward remains blocked."
    } else {
        "Accept the fixed replay decision and select a genuinely different existing-data hypothesis PlanOnly; do not tune this sample."
    }
    $manifest.status = "COMPLETED"; $manifest.final = $true; $manifest.stop_reason = "completed"
    $manifest.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); $manifest.finished_at = $manifest.updated_at
    $manifest.actual_duration_sec = [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)
    $manifest.monitor_pid = $null; $manifest.process_ids = @(); $manifest.rows = [int64]$report.history.total_source_rows
    $manifest.errors = 0; $manifest.exit_code = 0; $manifest.decision = [string]$report.decision
    $manifest.summary = $report.summary; $manifest.validation_gates = $report.validation.gates
    Write-JsonAtomic $manifest $manifestPath
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    foreach ($pair in @(
        @("status", "READY_FOR_POSTPROCESS"), @("gate_status", "READY_FOR_POSTPROCESS"),
        @("updated_at", $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")), @("monitor_pid", $null), @("process_ids", @()),
        @("final", $true), @("stop_reason", "completed"), @("expected_outputs_complete", $true),
        @("rows", [int64]$report.history.total_source_rows), @("errors", 0),
        @("actual_duration_sec", [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)),
        @("next_goal_decision", $nextDecision), @("next_goal_reason", [string]$report.decision),
        @("next_step_after_ready", $nextStep), @("raw_gate_next_step_after_ready", $nextStep)
    )) { Set-JsonProperty $gateDoc $pair[0] $pair[1] }
    Set-JsonProperty $gateDoc "last_cross_sectional_capitulation_output_path" $OutputPath
    Set-JsonProperty $gateDoc "last_cross_sectional_capitulation_manifest_path" $manifestPath
    Set-JsonProperty $gateDoc "last_cross_sectional_capitulation_decision" ([string]$report.decision)
    Set-JsonProperty $gateDoc "strategy_branch_status" ([ordered]@{
        branch = "cross_sectional_capitulation_rebound_4h_spot"; verdict = [string]$report.decision
        strategy_accepted = $false; research_candidate = [bool]$report.research_candidate
        paper_forward_allowed = $false; grid_allowed = $false; collect_allowed = $false; live_orders = $false
    })
    Write-JsonAtomic $gateDoc $gatePath
    $pointer.status = "READY_FOR_POSTPROCESS"; $pointer.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null; $pointer.process_ids = @(); $pointer.expected_outputs_complete = $true
    $pointer.verdict = [string]$report.decision; $pointer.next_goal_decision = $nextDecision
    Write-JsonAtomic $pointer $currentRunPath
    Write-Host ""
    Write-Host "Completed: $($report.decision)" -ForegroundColor Green
    Write-Host "Signals: $($report.summary.fixed_signal_candidates)"
    Write-Host "Trades: $($report.summary.executed_trades)"
    Write-Host "OOS expectancy: $($report.validation.oos.expectancy_bps) bps"
    Write-Host "Next: $nextStep"
} catch {
    $finishedAt = Get-Date
    $manifest.status = "FAILED"; $manifest.final = $false; $manifest.stop_reason = "failed_or_interrupted"
    $manifest.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); $manifest.finished_at = $manifest.updated_at
    $manifest.actual_duration_sec = [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)
    $manifest.monitor_pid = $null; $manifest.process_ids = @(); $manifest.errors = 1; $manifest.exit_code = $exitCode
    $manifest.error = $_.Exception.Message; Write-JsonAtomic $manifest $manifestPath
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    foreach ($pair in @(
        @("status", "STOPPED_INCOMPLETE"), @("gate_status", "STOPPED_INCOMPLETE"), @("updated_at", $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")),
        @("monitor_pid", $null), @("process_ids", @()), @("final", $false), @("stop_reason", "failed_or_interrupted"), @("errors", 1),
        @("next_goal_decision", "CROSS_SECTIONAL_CAPITULATION_REPLAY_STOPPED_INCOMPLETE"), @("next_goal_reason", $_.Exception.Message)
    )) { Set-JsonProperty $gateDoc $pair[0] $pair[1] }
    Write-JsonAtomic $gateDoc $gatePath
    $pointer.status = "STOPPED_INCOMPLETE"; $pointer.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null; $pointer.process_ids = @(); Write-JsonAtomic $pointer $currentRunPath
    Write-Host "Replay failed: $($_.Exception.Message)" -ForegroundColor Red
    throw
}
