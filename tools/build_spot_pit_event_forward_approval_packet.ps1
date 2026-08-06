param(
    [string]$PlanPath = "",
    [string]$PreflightPath = "",
    [string]$OutputPath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$analysisRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis"
$collectorPath = Join-Path $repoRoot "trading_mvp\src\spot_pit_event_collector.py"
$analyzerPath = Join-Path $repoRoot "trading_mvp\src\spot_pit_event_analyzer.py"
$readinessPath = Join-Path $repoRoot "trading_mvp\src\spot_pit_event_readiness.py"
$wrapperPath = Join-Path $repoRoot "tools\start_spot_pit_event_forward_visible.ps1"

function Resolve-Python {
    foreach ($candidate in @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    throw "Python runtime not found."
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Write-JsonAtomic {
    param($Object, [string]$Path)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $temp = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

$gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gateStatus.status -eq "RUNNING") { throw "Active run gate is RUNNING. Readiness work is blocked." }
if ([string]$gateStatus.status -eq "STOPPED_INCOMPLETE") { throw "Resolve or resume the incomplete run before replacing the gate." }
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($PlanPath)) { $PlanPath = [string]$gate.last_spot_pit_event_forward_plan_path }
if ([string]::IsNullOrWhiteSpace($PreflightPath)) { $PreflightPath = [string]$gate.last_spot_pit_event_public_preflight_path }
if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw "Plan not found: $PlanPath" }
if (-not (Test-Path -LiteralPath $PreflightPath -PathType Leaf)) { throw "Preflight not found: $PreflightPath" }
foreach ($path in @($collectorPath, $analyzerPath, $readinessPath, $wrapperPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Readiness source missing: $path" }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ([string]::IsNullOrWhiteSpace($OutputPath)) { $OutputPath = Join-Path $analysisRoot "spot_pit_event_forward_approval_packet_$stamp.json" }
$testEvidencePath = Join-Path $analysisRoot "spot_pit_event_forward_readiness_tests_$stamp.json"
$testLogPath = Join-Path $analysisRoot "spot_pit_event_forward_readiness_tests_$stamp.log"
if (-not (Test-Path -LiteralPath $analysisRoot)) { New-Item -ItemType Directory -Path $analysisRoot -Force | Out-Null }
$python = Resolve-Python
$testModules = @(
    "trading_mvp.tests.test_spot_pit_event_public_preflight",
    "trading_mvp.tests.test_spot_pit_event_collector",
    "trading_mvp.tests.test_spot_pit_event_analyzer",
    "trading_mvp.tests.test_spot_pit_event_readiness",
    "trading_mvp.tests.test_powershell_tooling"
)
$testCommand = "& `"$python`" -m unittest " + ($testModules -join " ") + " -v"
$testOutput = & $python -m unittest @testModules -v 2>&1 | Out-String
$testExit = $LASTEXITCODE
$testOutput | Set-Content -LiteralPath $testLogPath -Encoding UTF8
$match = [regex]::Match($testOutput, "Ran\s+(\d+)\s+tests?")
$testsRun = if ($match.Success) { [int]$match.Groups[1].Value } else { 0 }
$testEvidence = [ordered]@{
    schema = "spot_pit_event_forward_readiness_test_evidence_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    command = $testCommand
    modules = $testModules
    tests_run = $testsRun
    exit_code = $testExit
    passed = [bool]($testExit -eq 0 -and $testsRun -gt 0)
    log_path = $testLogPath
    log_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $testLogPath).Hash.ToLowerInvariant()
}
Write-JsonAtomic $testEvidence $testEvidencePath
if (-not $testEvidence.passed) { throw "Spot PIT event readiness tests failed. See $testLogPath" }

& $python $readinessPath `
    --plan $PlanPath `
    --preflight $PreflightPath `
    --collector $collectorPath `
    --analyzer $analyzerPath `
    --wrapper $wrapperPath `
    --test-evidence $testEvidencePath `
    --output $OutputPath
if ($LASTEXITCODE -ne 0) { throw "Approval packet builder rejected readiness. See $OutputPath" }
$packet = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
if (-not [bool]$packet.all_checks_passed) { throw "Approval packet checks did not pass." }

$readinessRunId = "spot_pit_event_forward_readiness_$stamp"
$now = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
Set-JsonProperty $gate "updated_at" $now
Set-JsonProperty $gate "run_id" $readinessRunId
Set-JsonProperty $gate "status" "READY_FOR_POSTPROCESS"
Set-JsonProperty $gate "gate_status" "READY_FOR_POSTPROCESS"
Set-JsonProperty $gate "purpose" "Sealed research-only spot PIT event forward collect readiness; awaiting explicit visible collect confirmation."
Set-JsonProperty $gate "started_at" $now
Set-JsonProperty $gate "requested_duration_sec" 0
Set-JsonProperty $gate "actual_duration_sec" 0
Set-JsonProperty $gate "completed_cycles" 0
Set-JsonProperty $gate "total_cycles" 0
Set-JsonProperty $gate "output_root" ([string]$packet.collection.output_root)
Set-JsonProperty $gate "output_path" $OutputPath
Set-JsonProperty $gate "output_kind" "file"
Set-JsonProperty $gate "manifest_path" $OutputPath
Set-JsonProperty $gate "final" $true
Set-JsonProperty $gate "stop_reason" "readiness_packet_completed"
Set-JsonProperty $gate "monitor_pid" $null
Set-JsonProperty $gate "collector_pid" $null
Set-JsonProperty $gate "process_ids" @()
Set-JsonProperty $gate "stale_monitor_pid" $null
Set-JsonProperty $gate "notification_required" $false
Set-JsonProperty $gate "launch_record_path" $null
Set-JsonProperty $gate "rows" 1
Set-JsonProperty $gate "errors" 0
Set-JsonProperty $gate "expected_outputs" ([ordered]@{ approval_packet = $OutputPath; test_evidence = $testEvidencePath; test_log = $testLogPath })
Set-JsonProperty $gate "expected_outputs_complete" $true
Set-JsonProperty $gate "next_goal_decision" ([string]$packet.decision)
Set-JsonProperty $gate "next_goal_reason" ([string]$packet.decision)
Set-JsonProperty $gate "next_step_after_ready" "Await explicit user confirmation, then start only through the visible wrapper. Replay/grid/paper/live/API keys remain blocked."
Set-JsonProperty $gate "raw_gate_next_step_after_ready" "Await explicit user confirmation, then start only through the visible wrapper."
Set-JsonProperty $gate "requires_explicit_user_approval_for_actual_collect" $true
Set-JsonProperty $gate "collect_allowed" $false
Set-JsonProperty $gate "replay_allowed" $false
Set-JsonProperty $gate "grid_allowed" $false
Set-JsonProperty $gate "paper_forward_allowed" $false
Set-JsonProperty $gate "live_orders" $false
Set-JsonProperty $gate "api_keys" $false
Set-JsonProperty $gate "leverage_or_margin" $false
Set-JsonProperty $gate "readiness_output_path" $OutputPath
Set-JsonProperty $gate "spot_pit_event_forward_approval_packet_path" $OutputPath
Set-JsonProperty $gate "spot_pit_event_forward_approval_packet_sha256" ((Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant())
Set-JsonProperty $gate "command_after_explicit_approval" ([string]$packet.command_after_explicit_approval)
Set-JsonProperty $gate "resume_command" $null
Set-JsonProperty $gate "strategy_branch_status" ([ordered]@{ branch = "spot_pit_idiosyncratic_crash_reclaim_1m"; verdict = "approval_packet_ready_awaiting_explicit_visible_confirmation"; strategy_accepted = $false; collect_allowed_now = $false; grid_allowed = $false; paper_forward_allowed = $false })
Set-JsonProperty $gate "verification" ([ordered]@{ targeted_readiness_tests_passed = $testsRun; targeted_readiness_status = "PASSED"; powershell_parse = "covered_by_test_powershell_tooling"; full_fast_shard = "pending_this_turn" })
Write-JsonAtomic $gate $gatePath

$pointer = [ordered]@{
    schema = "active_run_pointer_v1"
    project = "trading_mvp"
    run_id = $readinessRunId
    status = "READY_FOR_POSTPROCESS"
    updated_at = $now
    manifest_path = $OutputPath
    output = [ordered]@{ path = $OutputPath; kind = "file" }
    monitor_pid = $null
    collector_pid = $null
    process_ids = @()
    branch = "spot_pit_idiosyncratic_crash_reclaim_1m"
    strategy_accepted = $false
    expected_outputs = [ordered]@{ approval_packet = $OutputPath; test_evidence = $testEvidencePath; test_log = $testLogPath }
    expected_outputs_complete = $true
    verdict = [string]$packet.decision
    next_goal_decision = [string]$packet.decision
}
Write-JsonAtomic $pointer $currentRunPath

$result = [ordered]@{
    decision = [string]$packet.decision
    approval_packet_path = $OutputPath
    approval_packet_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
    test_evidence_path = $testEvidencePath
    tests_run = $testsRun
    command_after_explicit_approval = [string]$packet.command_after_explicit_approval
    would_start = $false
}
if ($Json) { $result | ConvertTo-Json -Depth 20 }
else {
    Write-Host "Spot PIT event forward approval packet is ready." -ForegroundColor Green
    Write-Host "Packet: $OutputPath"
    Write-Host "Tests: $testsRun passed"
    Write-Host "No collector was started. Explicit confirmation is still required." -ForegroundColor Yellow
}
