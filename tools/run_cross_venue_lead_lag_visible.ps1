param(
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_venue_spot_lead_lag_planonly_20260712_203040.json",
    [string]$ExpectedPlanSha256 = "9b271041fab3074c34c9916f7895240b9c078fe93d0c767d1929809bbb6403b3",
    [string]$InputPath = "",
    [string]$OutputPath = "",
    [string]$RunId = "",
    [long]$MaxRows = 0,
    [int]$ProgressEveryRows = 1000000,
    [string]$TempParent = "E:\ZolotyayLopata-data\exports\trading-mvp\run",
    [switch]$PlanOnly,
    [switch]$ConfirmedResearchScan,
    [switch]$VisibleChild,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\cross_venue_lead_lag.py"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$kind = if ($MaxRows -gt 0) { "smoke" } else { "full" }
if (-not $RunId) { $RunId = "cross_venue_spot_lead_lag_${kind}_$stamp" }
if (-not $OutputPath) {
    $OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\backtests\$RunId.json"
}
$runRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\run"
$manifestPath = Join-Path $runRoot "$RunId.manifest.json"
$consoleLogPath = Join-Path $runRoot "$RunId.console.log"

function Write-JsonAtomic {
    param($Value, [string]$Path)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temp = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    if (-not $candidates) { throw "No Python runtime found." }
    return $candidates[0]
}

function Read-GateStatus {
    if (-not (Test-Path -LiteralPath $gateChecker -PathType Leaf)) { return $null }
    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
    if ($LASTEXITCODE -ne 0) { throw "Active run gate check failed." }
    return ($raw | Out-String | ConvertFrom-Json)
}

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw "Plan not found: $PlanPath" }
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "Lead/lag module not found: $modulePath" }
$planHash = (Get-FileHash -LiteralPath $PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($planHash -ne $ExpectedPlanSha256.ToLowerInvariant()) {
    throw "Sealed plan hash mismatch: expected=$ExpectedPlanSha256 observed=$planHash"
}
$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
if ([string]$plan.schema -ne "cross_venue_spot_lead_lag_plan_v1") { throw "Unexpected plan schema: $($plan.schema)" }
if (-not [bool]$plan.research_only -or -not [bool]$plan.fixed_parameters_no_grid -or [bool]$plan.strategy_accepted) {
    throw "Plan must be fixed, research-only, no-grid and unaccepted."
}
if (-not $InputPath) { $InputPath = [string]$plan.input_path }
if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) { throw "Input not found: $InputPath" }
if ([System.IO.Path]::GetFullPath($InputPath) -ne [System.IO.Path]::GetFullPath([string]$plan.input_path)) {
    throw "Input differs from the sealed plan."
}
if ($MaxRows -lt 0) { throw "MaxRows cannot be negative." }
if ($ProgressEveryRows -le 0) { throw "ProgressEveryRows must be positive." }

$command = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
    "-PlanPath `"$PlanPath`"",
    "-ExpectedPlanSha256 $ExpectedPlanSha256",
    "-InputPath `"$InputPath`"",
    "-OutputPath `"$OutputPath`"",
    "-RunId $RunId",
    "-MaxRows $MaxRows",
    "-ProgressEveryRows $ProgressEveryRows",
    "-TempParent `"$TempParent`"",
    "-ConfirmedResearchScan -VisibleChild"
) -join " "

$preview = [ordered]@{
    schema = "cross_venue_spot_lead_lag_visible_plan_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    mode = "cross_venue_spot_lead_lag_visible_$kind"
    would_start = [bool]($ConfirmedResearchScan -and -not $PlanOnly)
    would_open_visible_terminal = [bool]($ConfirmedResearchScan -and -not $PlanOnly -and -not $VisibleChild)
    research_only = $true
    fixed_parameters_no_grid = $true
    run_id = $RunId
    input_path = $InputPath
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_path = $OutputPath
    manifest_path = $manifestPath
    console_log_path = $consoleLogPath
    temp_parent = $TempParent
    max_rows = $MaxRows
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    grid_search = $false
    collect = $false
    paper_forward_allowed = $false
    command = $command
}

if ($PlanOnly -or -not $ConfirmedResearchScan) {
    if ($Json) { $preview | ConvertTo-Json -Depth 20 } else { $preview | Format-List }
    exit 0
}

$gateStatus = Read-GateStatus
if ($gateStatus -and [string]$gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING for $($gateStatus.run_id); refusing a duplicate scan."
}

if (-not $VisibleChild) {
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $childArgs = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanSha256", $ExpectedPlanSha256,
        "-InputPath", $InputPath,
        "-OutputPath", $OutputPath,
        "-RunId", $RunId,
        "-MaxRows", [string]$MaxRows,
        "-ProgressEveryRows", [string]$ProgressEveryRows,
        "-TempParent", $TempParent,
        "-ConfirmedResearchScan", "-VisibleChild"
    )
    $terminal = Start-Process -FilePath $pwsh -ArgumentList $childArgs -WindowStyle Normal -PassThru
    $preview.mode = "cross_venue_spot_lead_lag_visible_terminal_launched"
    $preview.visible_terminal_pid = $terminal.Id
    if ($Json) { $preview | ConvertTo-Json -Depth 20 } else {
        Write-Host "Visible lead/lag scan launched." -ForegroundColor Cyan
        Write-Host "PID: $($terminal.Id)"
        Write-Host "RunId: $RunId"
        Write-Host "Output: $OutputPath"
        Write-Host "Status: pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
    }
    exit 0
}

$host.UI.RawUI.WindowTitle = "trading_mvp lead-lag $kind - $RunId"
New-Item -ItemType Directory -Force -Path $runRoot, (Split-Path -Parent $OutputPath), $TempParent | Out-Null
$driveName = ([System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($TempParent))).TrimEnd("\").TrimEnd(":")
$drive = Get-PSDrive -Name $driveName -ErrorAction Stop
$requiredFree = if ($MaxRows -gt 0) { 512MB } else { 3GB }
if ($drive.Free -lt $requiredFree) {
    throw "Insufficient free space on $driveName`: $([Math]::Round($drive.Free / 1GB, 2)) GiB; need at least $([Math]::Round($requiredFree / 1GB, 2)) GiB."
}

$startedAt = Get-Date
$expectedDurationSec = if ($MaxRows -gt 0) { 120 } else { 1800 }
$estimatedFinish = $startedAt.AddSeconds($expectedDurationSec)
$manifest = [ordered]@{
    schema = "cross_venue_spot_lead_lag_manifest_v1"
    project = "trading_mvp"
    run_id = $RunId
    run_type = "cross_venue_spot_lead_lag_fixed_$kind"
    status = "RUNNING"
    final = $false
    stop_reason = $null
    started_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    monitor_pid = $PID
    process_ids = @($PID)
    input_path = $InputPath
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_path = $OutputPath
    console_log_path = $consoleLogPath
    temp_parent = $TempParent
    max_rows = $MaxRows
    requested_duration_sec = $expectedDurationSec
    estimated_finish = $estimatedFinish.ToString("yyyy-MM-ddTHH:mm:sszzz")
    rows = 0
    errors = 0
    command = $command
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    grid_search = $false
    collect = $false
}
Write-JsonAtomic $manifest $manifestPath

$gate = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { [pscustomobject]@{} }
Set-JsonProperty $gate "schema" "active_run_gate_v2"
Set-JsonProperty $gate "project" "trading_mvp"
Set-JsonProperty $gate "status" "RUNNING"
Set-JsonProperty $gate "gate_status" "RUNNING"
Set-JsonProperty $gate "run_id" $RunId
Set-JsonProperty $gate "purpose" "Visible fixed-parameter MEXC/Gate spot lead/lag replay over existing clean WS data; research-only."
Set-JsonProperty $gate "updated_at" $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
Set-JsonProperty $gate "started_at" $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
Set-JsonProperty $gate "requested_duration_sec" $expectedDurationSec
Set-JsonProperty $gate "estimated_finish" $estimatedFinish.ToString("yyyy-MM-ddTHH:mm:sszzz")
Set-JsonProperty $gate "actual_duration_sec" $null
Set-JsonProperty $gate "monitor_pid" $PID
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @($PID)
Set-JsonProperty $gate "manifest_path" $manifestPath
Set-JsonProperty $gate "output_path" $OutputPath
Set-JsonProperty $gate "output_kind" "file"
Set-JsonProperty $gate "output" ([ordered]@{ path = $OutputPath; kind = "file" })
Set-JsonProperty $gate "expected_outputs" ([ordered]@{ lead_lag_report = $OutputPath })
Set-JsonProperty $gate "expected_outputs_complete" $false
Set-JsonProperty $gate "rows" 0
Set-JsonProperty $gate "errors" 0
Set-JsonProperty $gate "final" $false
Set-JsonProperty $gate "stop_reason" $null
Set-JsonProperty $gate "replay_allowed" $false
Set-JsonProperty $gate "grid_allowed" $false
Set-JsonProperty $gate "paper_forward_allowed" $false
Set-JsonProperty $gate "live_orders" $false
Set-JsonProperty $gate "api_keys" $false
Set-JsonProperty $gate "leverage_or_margin" $false
Set-JsonProperty $gate "next_goal_decision" "CROSS_VENUE_SPOT_LEAD_LAG_SCAN_RUNNING"
Set-JsonProperty $gate "next_goal_reason" "Visible fixed no-grid lead/lag scan is running. Only status/ETA checks are allowed."
Set-JsonProperty $gate "next_step_after_ready" "Inspect the final lead/lag report and its OOS/walk-forward/stress/economics gates."
Set-JsonProperty $gate "raw_gate_next_step_after_ready" $gate.next_step_after_ready
Set-JsonProperty $gate "lead_lag_plan_path" $PlanPath
Set-JsonProperty $gate "lead_lag_plan_sha256" $planHash
Write-JsonAtomic $gate $gatePath

$pointer = [ordered]@{
    schema = "active_run_pointer_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    manifest_path = $manifestPath
    output = [ordered]@{ path = $OutputPath; kind = "file" }
    source_path = $InputPath
    collector_pid = $null
    monitor_pid = $PID
    process_ids = @($PID)
    branch = "cross_venue_spot_lead_lag_spillover"
    strategy_accepted = $false
    expected_outputs = [ordered]@{ lead_lag_report = $OutputPath }
    expected_outputs_complete = $false
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "Cross-Venue Spot Lead/Lag Fixed Scan" -ForegroundColor Cyan
Write-Host "RunId: $RunId"
Write-Host "Mode: $kind"
Write-Host "Input: $InputPath"
Write-Host "Plan SHA256: $planHash"
Write-Host "Output: $OutputPath"
Write-Host "Temp: $TempParent"
Write-Host "Free space: $([Math]::Round($drive.Free / 1GB, 2)) GiB"
Write-Host "Scope: existing data only; no collect/grid/live/API/margin" -ForegroundColor Yellow

$python = Resolve-Python
$pythonArgs = @(
    $modulePath,
    "--input", $InputPath,
    "--plan", $PlanPath,
    "--expected-plan-sha256", $ExpectedPlanSha256,
    "--output", $OutputPath,
    "--max-rows", [string]$MaxRows,
    "--progress-every-rows", [string]$ProgressEveryRows,
    "--temp-parent", $TempParent
)

$exitCode = 1
try {
    & $python @pythonArgs 2>&1 | Tee-Object -FilePath $consoleLogPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Lead/lag Python scan exited with code $exitCode" }
    if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) { throw "Scan completed without report: $OutputPath" }
    $report = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    $scanComplete = [bool]$report.summary.scan_complete
    $decision = [string]$report.decision
    if (-not $scanComplete) {
        $nextDecision = "CROSS_VENUE_SPOT_LEAD_LAG_SMOKE_PASSED_READY_FOR_VISIBLE_FULL_SCAN"
        $nextStep = "Run the same sealed plan visibly without MaxRows. Do not interpret smoke economics."
    } elseif ([bool]$report.research_candidate) {
        $nextDecision = "CROSS_VENUE_SPOT_LEAD_LAG_CANDIDATE_REQUIRES_INDEPENDENT_AUDIT_PLANONLY"
        $nextStep = "Run a fail-closed independent artifact audit PlanOnly; paper-forward remains blocked until audit passes."
    } else {
        $nextDecision = $decision
        $nextStep = "Accept the report decision and select the next fixed existing-data hypothesis PlanOnly; do not tune this sample."
    }

    $finishedAt = Get-Date
    $manifest.status = "COMPLETED"
    $manifest.final = $true
    $manifest.stop_reason = "completed"
    $manifest.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $manifest.finished_at = $manifest.updated_at
    $manifest.actual_duration_sec = [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)
    $manifest.monitor_pid = $null
    $manifest.process_ids = @()
    $manifest.rows = [int64]$report.partition.rows_read
    $manifest.errors = 0
    $manifest.exit_code = 0
    $manifest.decision = $decision
    $manifest.summary = $report.summary
    $manifest.validation_gates = $report.validation.gates
    Write-JsonAtomic $manifest $manifestPath

    $gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty $gate "status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gate "gate_status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gate "updated_at" $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    Set-JsonProperty $gate "monitor_pid" $null
    Set-JsonProperty $gate "process_ids" @()
    Set-JsonProperty $gate "final" $true
    Set-JsonProperty $gate "stop_reason" "completed"
    Set-JsonProperty $gate "actual_duration_sec" ([Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1))
    Set-JsonProperty $gate "expected_outputs_complete" $true
    Set-JsonProperty $gate "rows" ([int64]$report.partition.rows_read)
    Set-JsonProperty $gate "errors" 0
    Set-JsonProperty $gate "next_goal_decision" $nextDecision
    Set-JsonProperty $gate "next_goal_reason" $decision
    Set-JsonProperty $gate "next_step_after_ready" $nextStep
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" $nextStep
    Set-JsonProperty $gate "last_cross_venue_lead_lag_output_path" $OutputPath
    Set-JsonProperty $gate "last_cross_venue_lead_lag_manifest_path" $manifestPath
    Set-JsonProperty $gate "last_cross_venue_lead_lag_decision" $decision
    Set-JsonProperty $gate "strategy_branch_status" ([ordered]@{
        branch = "cross_venue_spot_lead_lag_spillover"
        verdict = $decision
        strategy_accepted = $false
        research_candidate = [bool]$report.research_candidate
        paper_forward_allowed = $false
        live_orders = $false
        next_step_required = $nextStep
    })
    Write-JsonAtomic $gate $gatePath

    $pointer.status = "READY_FOR_POSTPROCESS"
    $pointer.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null
    $pointer.process_ids = @()
    $pointer.expected_outputs_complete = $true
    $pointer.verdict = $decision
    $pointer.next_goal_decision = $nextDecision
    Write-JsonAtomic $pointer $currentRunPath

    Write-Host ""
    Write-Host "Completed: $decision" -ForegroundColor Green
    Write-Host "Rows: $($report.partition.rows_read)"
    Write-Host "Signals: $($report.summary.signals)"
    Write-Host "Baseline trades: $($report.summary.baseline_trades)"
    Write-Host "OOS expectancy: $($report.validation.oos.expectancy_bps) bps"
    Write-Host "Next: $nextStep"
} catch {
    $finishedAt = Get-Date
    $manifest.status = "FAILED"
    $manifest.final = $false
    $manifest.stop_reason = "failed_or_interrupted"
    $manifest.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $manifest.finished_at = $manifest.updated_at
    $manifest.actual_duration_sec = [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)
    $manifest.monitor_pid = $null
    $manifest.process_ids = @()
    $manifest.errors = 1
    $manifest.exit_code = $exitCode
    $manifest.error = $_.Exception.Message
    Write-JsonAtomic $manifest $manifestPath
    $gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty $gate "status" "STOPPED_INCOMPLETE"
    Set-JsonProperty $gate "gate_status" "STOPPED_INCOMPLETE"
    Set-JsonProperty $gate "updated_at" $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    Set-JsonProperty $gate "monitor_pid" $null
    Set-JsonProperty $gate "process_ids" @()
    Set-JsonProperty $gate "final" $false
    Set-JsonProperty $gate "stop_reason" "failed_or_interrupted"
    Set-JsonProperty $gate "actual_duration_sec" ([Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1))
    Set-JsonProperty $gate "errors" 1
    Set-JsonProperty $gate "next_goal_decision" "CROSS_VENUE_SPOT_LEAD_LAG_STOPPED_INCOMPLETE"
    Set-JsonProperty $gate "next_goal_reason" $_.Exception.Message
    Set-JsonProperty $gate "next_step_after_ready" "Inspect the visible console log, clean orphan temp partitions, then restart the same sealed scan visibly."
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" $gate.next_step_after_ready
    Write-JsonAtomic $gate $gatePath
    $pointer.status = "STOPPED_INCOMPLETE"
    $pointer.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null
    $pointer.process_ids = @()
    Write-JsonAtomic $pointer $currentRunPath
    Write-Host "Lead/lag scan failed: $($_.Exception.Message)" -ForegroundColor Red
    throw
}
