param(
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_planonly_20260712_2145.json",
    [string]$ExpectedPlanSha256 = "ae63d46f7aed2fd0cf3b87420d3e834d820805254d6b8a2c0f1f60ea85cdcccb",
    [string]$OutputPath = "",
    [string]$RunId = "",
    [switch]$PlanOnly,
    [switch]$ConfirmedPublicPreflight,
    [switch]$VisibleChild,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$modulePath = Join-Path $repoRoot "trading_mvp\src\spot_pit_event_public_preflight.py"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $RunId) { $RunId = "spot_pit_event_public_preflight_$stamp" }
if (-not $OutputPath) { $OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\$RunId.json" }
$runRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\run"
$manifestPath = Join-Path $runRoot "$RunId.manifest.json"
$consoleLogPath = Join-Path $runRoot "$RunId.console.log"

function Write-JsonAtomic {
    param($Value, [string]$Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $temp = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Set-P {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw "Plan missing: $PlanPath" }
$planHash = (Get-FileHash -LiteralPath $PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($planHash -ne $ExpectedPlanSha256.ToLowerInvariant()) { throw "Plan hash mismatch: expected=$ExpectedPlanSha256 observed=$planHash" }
$command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -PlanPath `"$PlanPath`" -ExpectedPlanSha256 $ExpectedPlanSha256 -OutputPath `"$OutputPath`" -RunId $RunId -ConfirmedPublicPreflight -VisibleChild"
$preview = [ordered]@{
    schema = "spot_pit_event_public_preflight_visible_plan_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    would_start = [bool]($ConfirmedPublicPreflight -and -not $PlanOnly)
    would_open_visible_terminal = [bool]($ConfirmedPublicPreflight -and -not $PlanOnly -and -not $VisibleChild)
    research_only = $true
    run_id = $RunId
    plan_path = $PlanPath
    plan_sha256 = $planHash
    output_path = $OutputPath
    manifest_path = $manifestPath
    console_log_path = $consoleLogPath
    actual_collect = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    command = $command
}
if ($PlanOnly -or -not $ConfirmedPublicPreflight) {
    if ($Json) { $preview | ConvertTo-Json -Depth 20 } else { $preview | Format-List }
    exit 0
}
$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -eq "RUNNING") { throw "Active run gate is RUNNING for $($gate.run_id)." }

if (-not $VisibleChild) {
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $args = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
        "-PlanPath", $PlanPath, "-ExpectedPlanSha256", $ExpectedPlanSha256,
        "-OutputPath", $OutputPath, "-RunId", $RunId,
        "-ConfirmedPublicPreflight", "-VisibleChild"
    )
    $terminal = Start-Process -FilePath $pwsh -ArgumentList $args -WindowStyle Normal -PassThru
    $preview.mode = "spot_pit_event_public_preflight_visible_terminal_launched"
    $preview.visible_terminal_pid = $terminal.Id
    if ($Json) { $preview | ConvertTo-Json -Depth 20 } else { $preview | Format-List }
    exit 0
}

$host.UI.RawUI.WindowTitle = "trading_mvp spot PIT public preflight - $RunId"
New-Item -ItemType Directory -Force -Path $runRoot, (Split-Path -Parent $OutputPath) | Out-Null
$python = "C:\Program Files\Python313\python.exe"
$startedAt = Get-Date
$manifest = [ordered]@{
    schema = "spot_pit_event_public_preflight_manifest_v1"; project = "trading_mvp"; run_id = $RunId
    status = "RUNNING"; final = $false; stop_reason = $null
    started_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    requested_duration_sec = 300; monitor_pid = $PID; process_ids = @($PID)
    plan_path = $PlanPath; plan_sha256 = $planHash; output_path = $OutputPath; console_log_path = $consoleLogPath
    rows = 0; errors = 0; research_only = $true; actual_collect = $false; live_orders = $false; api_keys = $false; leverage_or_margin = $false
}
Write-JsonAtomic $manifest $manifestPath
$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
foreach ($pair in @(
    @("status", "RUNNING"), @("gate_status", "RUNNING"), @("run_id", $RunId),
    @("purpose", "Short visible public endpoint/schema preflight for future spot PIT event research; not a collector."),
    @("updated_at", $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")), @("started_at", $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")),
    @("monitor_pid", $PID), @("process_ids", @($PID)), @("manifest_path", $manifestPath), @("output_path", $OutputPath),
    @("output_kind", "file"), @("expected_outputs_complete", $false), @("final", $false), @("rows", 0), @("errors", 0),
    @("next_goal_decision", "SPOT_PIT_EVENT_PUBLIC_PREFLIGHT_RUNNING"),
    @("next_goal_reason", "Short public preflight is running; no collector or other engineering step may start."),
    @("next_step_after_ready", "Inspect endpoint/schema/coverage result; actual collector remains blocked."),
    @("replay_allowed", $false), @("collect_allowed", $false), @("grid_allowed", $false), @("paper_forward_allowed", $false)
)) { Set-P $gateDoc $pair[0] $pair[1] }
Set-P $gateDoc "raw_gate_next_step_after_ready" $gateDoc.next_step_after_ready
Set-P $gateDoc "output" ([ordered]@{ path = $OutputPath; kind = "file" })
Set-P $gateDoc "expected_outputs" ([ordered]@{ public_preflight = $OutputPath })
Write-JsonAtomic $gateDoc $gatePath
$pointer = [ordered]@{
    schema = "active_run_pointer_v1"; project = "trading_mvp"; run_id = $RunId; status = "RUNNING"
    updated_at = $startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); manifest_path = $manifestPath
    output = [ordered]@{ path = $OutputPath; kind = "file" }; monitor_pid = $PID; collector_pid = $null; process_ids = @($PID)
    branch = "spot_pit_idiosyncratic_crash_reclaim_1m"; strategy_accepted = $false
    expected_outputs = [ordered]@{ public_preflight = $OutputPath }; expected_outputs_complete = $false
}
Write-JsonAtomic $pointer $currentRunPath

Write-Host "Spot PIT Event Public Preflight" -ForegroundColor Cyan
Write-Host "RunId: $RunId"
Write-Host "Plan SHA256: $planHash"
Write-Host "Output: $OutputPath"
Write-Host "Scope: public endpoints only; NOT the 14-day collector" -ForegroundColor Yellow
$exitCode = 1
try {
    & $python $modulePath --plan $PlanPath --expected-plan-sha256 $ExpectedPlanSha256 --output $OutputPath --timeout-sec 15 2>&1 | Tee-Object -FilePath $consoleLogPath
    $exitCode = $LASTEXITCODE
    $report = if (Test-Path -LiteralPath $OutputPath) { Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json } else { $null }
    if (-not $report) { throw "Preflight produced no report (exit=$exitCode)." }
    $finishedAt = Get-Date
    $accepted = [bool]$report.accepted
    $nextDecision = if ($accepted) { "SPOT_PIT_EVENT_PUBLIC_PREFLIGHT_ACCEPTED_READY_FOR_COLLECTOR_IMPLEMENTATION" } else { "SPOT_PIT_EVENT_PUBLIC_PREFLIGHT_REJECTED_FIX_BEFORE_COLLECTOR" }
    $nextStep = if ($accepted) { "Implement durable segmented collector and replay contract with mocks. Do not start the 14-day run yet." } else { "Fix only reported endpoint/schema/coverage failures, then repeat the short visible preflight." }
    $manifest.status = "COMPLETED"; $manifest.final = $true; $manifest.stop_reason = "completed"
    $manifest.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); $manifest.finished_at = $manifest.updated_at
    $manifest.actual_duration_sec = [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1); $manifest.monitor_pid = $null; $manifest.process_ids = @()
    $manifest.rows = [int]$report.coverage.frozen_candidates; $manifest.errors = $report.errors.PSObject.Properties.Count
    $manifest.exit_code = $exitCode; $manifest.decision = [string]$report.decision; $manifest.coverage = $report.coverage
    Write-JsonAtomic $manifest $manifestPath
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    foreach ($pair in @(
        @("status", "READY_FOR_POSTPROCESS"), @("gate_status", "READY_FOR_POSTPROCESS"), @("updated_at", $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")),
        @("monitor_pid", $null), @("process_ids", @()), @("final", $true), @("stop_reason", "completed"), @("expected_outputs_complete", $true),
        @("rows", [int]$report.coverage.frozen_candidates), @("errors", $report.errors.PSObject.Properties.Count),
        @("actual_duration_sec", [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)),
        @("next_goal_decision", $nextDecision), @("next_goal_reason", [string]$report.decision),
        @("next_step_after_ready", $nextStep), @("raw_gate_next_step_after_ready", $nextStep),
        @("requires_explicit_user_approval_for_actual_collect", $true), @("collect_allowed", $false)
    )) { Set-P $gateDoc $pair[0] $pair[1] }
    Set-P $gateDoc "last_spot_pit_event_public_preflight_path" $OutputPath
    Set-P $gateDoc "last_spot_pit_event_public_preflight_decision" ([string]$report.decision)
    Write-JsonAtomic $gateDoc $gatePath
    $pointer.status = "READY_FOR_POSTPROCESS"; $pointer.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    $pointer.monitor_pid = $null; $pointer.process_ids = @(); $pointer.expected_outputs_complete = $true
    $pointer.verdict = [string]$report.decision; $pointer.next_goal_decision = $nextDecision
    Write-JsonAtomic $pointer $currentRunPath
    Write-Host "Completed: $($report.decision)" -ForegroundColor $(if ($accepted) { "Green" } else { "Yellow" })
    Write-Host "Frozen candidates: $($report.coverage.frozen_candidates); two venue: $($report.coverage.two_venue_candidates)"
    Write-Host "Next: $nextStep"
} catch {
    $finishedAt = Get-Date
    $manifest.status = "FAILED"; $manifest.final = $false; $manifest.stop_reason = "failed_or_interrupted"
    $manifest.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); $manifest.errors = 1; $manifest.exit_code = $exitCode; $manifest.error = $_.Exception.Message
    $manifest.monitor_pid = $null; $manifest.process_ids = @(); Write-JsonAtomic $manifest $manifestPath
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    foreach ($pair in @(
        @("status", "STOPPED_INCOMPLETE"), @("gate_status", "STOPPED_INCOMPLETE"), @("updated_at", $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")),
        @("monitor_pid", $null), @("process_ids", @()), @("final", $false), @("errors", 1),
        @("next_goal_decision", "SPOT_PIT_EVENT_PUBLIC_PREFLIGHT_STOPPED_INCOMPLETE"), @("next_goal_reason", $_.Exception.Message)
    )) { Set-P $gateDoc $pair[0] $pair[1] }
    Write-JsonAtomic $gateDoc $gatePath
    $pointer.status = "STOPPED_INCOMPLETE"; $pointer.updated_at = $finishedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"); $pointer.monitor_pid = $null; $pointer.process_ids = @()
    Write-JsonAtomic $pointer $currentRunPath
    throw
}
