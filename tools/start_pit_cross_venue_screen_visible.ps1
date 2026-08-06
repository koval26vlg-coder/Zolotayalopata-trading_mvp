param(
    [string]$SpecPath = "",
    [string]$OutputPath = "",
    [string]$PriorSpotReportPath = "",
    [string]$RunId = "",
    [double]$RoundTripFeeBps = 39.0,
    [double]$SlippageBps = 10.0,
    [double]$OperationalBufferBps = 20.0,
    [int]$MaxEvents = 1000,
    [int]$ProgressEveryRows = 50000,
    [switch]$ConfirmedResearchScreen,
    [switch]$RunInCurrentTerminal,
    [switch]$PlanOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\pit_cross_venue_screen.py"
$analysisRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis"
$runRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\run"
$allowedDecision = "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param($Object, [string]$Path)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $tempPath = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Resolve-LatestSpec {
    $roots = @(
        (Join-Path $repoRoot "exports\trading-mvp\analysis"),
        $analysisRoot
    )
    $candidate = $roots |
        Where-Object { Test-Path -LiteralPath $_ } |
        ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter "pit_two_venue_clean_slice_spec_planonly_*.json" -File } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "PIT clean-slice spec not found."
    }
    return $candidate.FullName
}

function Quote-CommandArg([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

if ([string]::IsNullOrWhiteSpace($SpecPath)) {
    $SpecPath = Resolve-LatestSpec
}
$SpecPath = (Resolve-Path -LiteralPath $SpecPath).Path
if ([string]::IsNullOrWhiteSpace($PriorSpotReportPath)) {
    $PriorSpotReportPath = Join-Path $repoRoot "exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"
}
$PriorSpotReportPath = (Resolve-Path -LiteralPath $PriorSpotReportPath).Path

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "pit_linear_perp_cross_venue_screen_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $analysisRoot "$RunId.json"
}
$manifestPath = Join-Path $runRoot "$RunId.manifest.json"
$consoleLogPath = Join-Path $runRoot "$RunId.console.log"
$python = Resolve-Python

$gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ([string]$gateStatus.status -eq "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resolve the incomplete run before screening."
}
$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]$gateDoc.next_goal_decision -ne $allowedDecision) {
    throw "PIT linear-perp screen is not the active gate step. next_goal_decision=$($gateDoc.next_goal_decision)"
}
if ([bool]$gateDoc.replay_allowed) {
    throw "Fail-closed guard: replay_allowed must remain false for screening."
}

$innerCommand = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File", (Quote-CommandArg $PSCommandPath),
    "-SpecPath", (Quote-CommandArg $SpecPath),
    "-OutputPath", (Quote-CommandArg $OutputPath),
    "-PriorSpotReportPath", (Quote-CommandArg $PriorSpotReportPath),
    "-RunId", $RunId,
    "-RoundTripFeeBps", $RoundTripFeeBps,
    "-SlippageBps", $SlippageBps,
    "-OperationalBufferBps", $OperationalBufferBps,
    "-MaxEvents", $MaxEvents,
    "-ProgressEveryRows", $ProgressEveryRows,
    "-ConfirmedResearchScreen -RunInCurrentTerminal"
) -join " "

$plan = [ordered]@{
    schema = "pit_linear_perp_cross_venue_screen_visible_plan_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    mode = "pit_linear_perp_cross_venue_screen_visible"
    would_start = [bool]($ConfirmedResearchScreen -and -not $PlanOnly)
    would_open_visible_terminal = [bool]($ConfirmedResearchScreen -and -not $PlanOnly -and -not $RunInCurrentTerminal)
    research_only = $true
    screening_only = $true
    clean_slice_materialized = $false
    replay_allowed = $false
    grid_allowed = $false
    backtest_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    run_id = $RunId
    spec_path = $SpecPath
    prior_spot_report_path = $PriorSpotReportPath
    output_path = $OutputPath
    manifest_path = $manifestPath
    console_log_path = $consoleLogPath
    total_cost_bps = $RoundTripFeeBps + $SlippageBps + $OperationalBufferBps
    command = $innerCommand
}

if ($PlanOnly -or -not $ConfirmedResearchScreen) {
    if ($Json) {
        $plan | ConvertTo-Json -Depth 12
    } else {
        $plan | Format-List
    }
    exit 0
}

if (-not $RunInCurrentTerminal) {
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $args = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
        "-SpecPath", $SpecPath,
        "-OutputPath", $OutputPath,
        "-PriorSpotReportPath", $PriorSpotReportPath,
        "-RunId", $RunId,
        "-RoundTripFeeBps", [string]$RoundTripFeeBps,
        "-SlippageBps", [string]$SlippageBps,
        "-OperationalBufferBps", [string]$OperationalBufferBps,
        "-MaxEvents", [string]$MaxEvents,
        "-ProgressEveryRows", [string]$ProgressEveryRows,
        "-ConfirmedResearchScreen", "-RunInCurrentTerminal"
    )
    $visible = Start-Process -FilePath $pwsh -ArgumentList $args -PassThru
    $launch = [ordered]@{
        schema = "pit_linear_perp_cross_venue_screen_visible_launch_v1"
        launched_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        visible_terminal_pid = $visible.Id
        run_id = $RunId
        output_path = $OutputPath
        manifest_path = $manifestPath
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
    }
    if ($Json) {
        $launch | ConvertTo-Json -Depth 8
    } else {
        Write-Host "Visible PIT linear-perp screen launched." -ForegroundColor Cyan
        Write-Host "PID: $($visible.Id)"
        Write-Host "RunId: $RunId"
        Write-Host "Output: $OutputPath"
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $analysisRoot, $runRoot | Out-Null
$startedAt = Get-Date
$manifest = [ordered]@{
    schema = "pit_linear_perp_cross_venue_screen_manifest_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    final = $false
    stop_reason = $null
    rows = 0
    completed_cycles = 0
    errors = 0
    started_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    pid = $PID
    command = $innerCommand
    spec_path = $SpecPath
    output_path = $OutputPath
    console_log_path = $consoleLogPath
    research_only = $true
    screening_only = $true
    replay_allowed = $false
    live_orders = $false
    api_keys = $false
}
Write-JsonAtomic $manifest $manifestPath

Set-JsonProperty $gateDoc "status" "RUNNING"
Set-JsonProperty $gateDoc "gate_status" "RUNNING"
Set-JsonProperty $gateDoc "run_id" $RunId
Set-JsonProperty $gateDoc "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty $gateDoc "purpose" "Research-only streaming linear-perp cross-venue screening over immutable PIT clean-slice mask; not spot, replay or backtest."
Set-JsonProperty $gateDoc "monitor_pid" $PID
Set-JsonProperty $gateDoc "collector_pid" $null
Set-JsonProperty $gateDoc "process_ids" @($PID)
Set-JsonProperty $gateDoc "manifest_path" $manifestPath
Set-JsonProperty $gateDoc "output_path" $OutputPath
Set-JsonProperty $gateDoc "output_kind" "json"
Set-JsonProperty $gateDoc "output" ([ordered]@{ path = $OutputPath; kind = "file" })
Set-JsonProperty $gateDoc "final" $false
Set-JsonProperty $gateDoc "expected_outputs_complete" $false
Set-JsonProperty $gateDoc "next_goal_decision" "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_RUNNING"
Set-JsonProperty $gateDoc "next_goal_reason" "Visible streaming screen is running. Only status/ETA checks are allowed."
Set-JsonProperty $gateDoc "next_step_after_ready" "Inspect the final screening report; keep replay/grid/backtest/paper/live/API blocked."
Set-JsonProperty $gateDoc "raw_gate_next_step_after_ready" $gateDoc.next_step_after_ready
Set-JsonProperty $gateDoc "replay_allowed" $false
Set-JsonProperty $gateDoc "grid_allowed" $false
Set-JsonProperty $gateDoc "backtest_allowed" $false
Set-JsonProperty $gateDoc "paper_forward_allowed" $false
Set-JsonProperty $gateDoc "live_orders" $false
Set-JsonProperty $gateDoc "api_keys" $false
Set-JsonProperty $gateDoc "leverage_or_margin" $false
Write-JsonAtomic $gateDoc $gatePath

$pointer = [ordered]@{
    schema = "active_run_pointer_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    manifest_path = $manifestPath
    output = [ordered]@{ path = $OutputPath; kind = "file" }
    collector_pid = $null
    monitor_pid = $PID
    process_ids = @($PID)
    launch_record_path = $null
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "PIT Linear-Perp Cross-Venue Screen" -ForegroundColor Cyan
Write-Host "RunId: $RunId"
Write-Host "Spec: $SpecPath"
Write-Host "Output: $OutputPath"
Write-Host "Fixed cost hurdle: $($RoundTripFeeBps + $SlippageBps + $OperationalBufferBps) bps"
Write-Host "Scope: screening only; NOT spot/replay/backtest" -ForegroundColor Yellow

$pythonArgs = @(
    $modulePath,
    "--spec", $SpecPath,
    "--out", $OutputPath,
    "--round-trip-fee-bps", [string]$RoundTripFeeBps,
    "--slippage-bps", [string]$SlippageBps,
    "--operational-buffer-bps", [string]$OperationalBufferBps,
    "--max-events", [string]$MaxEvents,
    "--progress-every-rows", [string]$ProgressEveryRows,
    "--prior-spot-report", $PriorSpotReportPath
)

$exitCode = 1
try {
    & $python @pythonArgs 2>&1 | Tee-Object -FilePath $consoleLogPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Python screen exited with code $exitCode"
    }
    $report = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    $nextDecision = if ([int]$report.summary.cost_positive_events -gt 0) {
        "PIT_LINEAR_PERP_SCREEN_COMPLETED_CANDIDATES_REQUIRE_DEEPER_EVIDENCE_PLANONLY"
    } else {
        "PIT_LINEAR_PERP_SCREEN_REJECTED_SELECT_NEXT_HYPOTHESIS_PLANONLY"
    }
    $nextStep = if ([int]$report.summary.cost_positive_events -gt 0) {
        "Run a PlanOnly evidence-gap gate for contract multipliers, executable depth, exact quote age and funding. Do not replay/backtest/grid/paper/live/API."
    } else {
        "Accept the screening rejection under base costs and select a new structural hypothesis PlanOnly. Do not replay/grid/paper/live/API."
    }
    $manifest.status = "COMPLETED"
    $manifest.final = $true
    $manifest.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $manifest.finished_at = $manifest.updated_at
    $manifest.exit_code = 0
    $manifest.decision = $report.decision
    $manifest.summary = $report.summary
    $manifest.rows = [int64]$report.summary.source_rows
    $manifest.completed_cycles = [int]$report.summary.source_cycles_seen
    $manifest.errors = 0
    $manifest.stop_reason = "completed"
    Write-JsonAtomic $manifest $manifestPath

    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty $gateDoc "status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gateDoc "gate_status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gateDoc "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gateDoc "monitor_pid" $null
    Set-JsonProperty $gateDoc "process_ids" @()
    Set-JsonProperty $gateDoc "final" $true
    Set-JsonProperty $gateDoc "stop_reason" "completed"
    Set-JsonProperty $gateDoc "expected_outputs_complete" $true
    Set-JsonProperty $gateDoc "rows" ([int64]$report.summary.source_rows)
    Set-JsonProperty $gateDoc "errors" 0
    Set-JsonProperty $gateDoc "next_goal_decision" $nextDecision
    Set-JsonProperty $gateDoc "next_goal_reason" ([string]$report.decision)
    Set-JsonProperty $gateDoc "next_step_after_ready" $nextStep
    Set-JsonProperty $gateDoc "raw_gate_next_step_after_ready" $nextStep
    Set-JsonProperty $gateDoc "last_pit_linear_perp_screen_output_path" $OutputPath
    Set-JsonProperty $gateDoc "last_pit_linear_perp_screen_manifest_path" $manifestPath
    Set-JsonProperty $gateDoc "last_pit_linear_perp_screen_decision" ([string]$report.decision)
    Set-JsonProperty $gateDoc "last_pit_linear_perp_screen_cost_positive_events" ([int]$report.summary.cost_positive_events)
    Set-JsonProperty $gateDoc "last_pit_linear_perp_screen_max_net_bps" $report.summary.max_net_screening_edge_bps
    Set-JsonProperty $gateDoc "strategy_branch_status" ([ordered]@{
        branch = "pit_linear_perp_cross_venue_screening"
        verdict = if ([int]$report.summary.cost_positive_events -gt 0) { "screening_candidates_unvalidated" } else { "screening_rejected_no_edge_after_base_costs" }
        source_instrument = "linear_perp"
        supports_spot_objective = $false
        strategy_accepted = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = $nextStep
    })
    Write-JsonAtomic $gateDoc $gatePath

    $pointer.status = "READY_FOR_POSTPROCESS"
    $pointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null
    $pointer.process_ids = @()
    Write-JsonAtomic $pointer $currentRunPath
    Write-Host "Completed: $($report.decision)" -ForegroundColor Green
    Write-Host "Cost-positive events: $($report.summary.cost_positive_events)"
} catch {
    $manifest.status = "FAILED"
    $manifest.final = $false
    $manifest.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $manifest.finished_at = $manifest.updated_at
    $manifest.exit_code = $exitCode
    $manifest.error = $_.Exception.Message
    $manifest.stop_reason = "failed"
    $manifest.errors = 1
    Write-JsonAtomic $manifest $manifestPath
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty $gateDoc "status" "STOPPED_INCOMPLETE"
    Set-JsonProperty $gateDoc "gate_status" "STOPPED_INCOMPLETE"
    Set-JsonProperty $gateDoc "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gateDoc "monitor_pid" $null
    Set-JsonProperty $gateDoc "process_ids" @()
    Set-JsonProperty $gateDoc "next_goal_decision" "PIT_LINEAR_PERP_SCREEN_FAILED_REVIEW_BEFORE_RERUN"
    Set-JsonProperty $gateDoc "next_goal_reason" $_.Exception.Message
    Write-JsonAtomic $gateDoc $gatePath
    $pointer.status = "STOPPED_INCOMPLETE"
    $pointer.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null
    $pointer.process_ids = @()
    Write-JsonAtomic $pointer $currentRunPath
    throw
}
