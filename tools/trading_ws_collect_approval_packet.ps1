param(
    [string]$OutputPath = "exports\trading-mvp\analysis\trading_ws_collect_approval_packet_current.json",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$edgePreflightScript = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$nextGoalStepScript = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$goalStatusScript = Join-Path $repoRoot "tools\trading_goal_status.ps1"
$readinessScript = Join-Path $repoRoot "tools\trading_ws_collect_readiness.ps1"
$approvalContractScript = Join-Path $repoRoot "tools\trading_collect_approval_contract.ps1"
$swarmStatusScript = Join-Path $repoRoot "tools\trading_swarm_status.ps1"
$testRunnerScript = Join-Path $repoRoot "tools\run_trading_tests.ps1"
$startWsCollectScript = Join-Path $repoRoot "tools\start_ws_collect_visible.ps1"
$runMvpScript = Join-Path $repoRoot "trading_mvp\run_mvp.ps1"
$wsCollectorPy = Join-Path $repoRoot "trading_mvp\src\ws_collector.py"
$postprocessScript = Join-Path $repoRoot "tools\run_ws_postprocess_visible.ps1"
$replayValidationScript = Join-Path $repoRoot "tools\run_ws_replay_validation_visible.ps1"
$confirmedShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"
$previewShortcut = Join-Path $repoRoot "TRADING_PREVIEW_DENSE_WS.cmd"
$planPreviewLatest = Join-Path $repoRoot "exports\trading-mvp\run\ws_collect_plan_preview_latest.json"

function Resolve-RepoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function Add-Check {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Name,
        [string]$Status,
        [string]$Evidence,
        [string]$Action = ""
    )
    $Checks.Add([ordered]@{
        name = $Name
        status = $Status
        evidence = $Evidence
        action = $Action
    }) | Out-Null
}

function Invoke-JsonScript {
    param(
        [string]$Path,
        [string[]]$Arguments = @()
    )
    $output = & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String).Trim()
    if ($exitCode -ne 0) {
        throw "$Path exited with code $exitCode. Output: $text"
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "$Path returned empty output."
    }
    return ($text | ConvertFrom-Json)
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing JSON file: $Path"
    }
    return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
}

function Has-Property {
    param(
        [object]$Object,
        [string]$Name
    )
    return ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name)
}

function Test-CommandContains {
    param(
        [string]$Command,
        [string]$Needle
    )
    return (-not [string]::IsNullOrWhiteSpace($Command) -and $Command -match [regex]::Escape($Needle))
}

function Get-FileFingerprint {
    param([string]$Path)
    $resolved = Resolve-RepoPath -Path $Path
    $result = [ordered]@{
        path = $resolved
        exists = $false
        bytes = 0
        last_write = $null
        sha256 = ""
    }
    if (-not (Test-Path -LiteralPath $resolved)) {
        return [pscustomobject]$result
    }
    $item = Get-Item -LiteralPath $resolved
    $hash = Get-FileHash -LiteralPath $resolved -Algorithm SHA256
    $result.exists = $true
    $result.bytes = [int64]$item.Length
    $result.last_write = $item.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz")
    $result.sha256 = $hash.Hash.ToLowerInvariant()
    return [pscustomobject]$result
}

$checks = [System.Collections.Generic.List[object]]::new()
$gate = $null
$preflight = $null
$nextGoal = $null
$goalStatus = $null
$readiness = $null
$approvalContract = $null
$swarmStatus = $null
$testPlan = $null
$planPreview = $null

try {
    $gate = Invoke-JsonScript -Path $gateChecker -Arguments @("-Json")
    if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        Add-Check $checks "active_run_gate" "fail" "Gate status is $($gate.status); only status/resume handling is allowed." "Do not create a start packet until the gate is not RUNNING or STOPPED_INCOMPLETE."
    } else {
        Add-Check $checks "active_run_gate" "pass" "Gate status=$($gate.status); run_id=$($gate.run_id); replay_allowed=$($gate.replay_allowed)."
    }
} catch {
    Add-Check $checks "active_run_gate" "fail" "Could not read active-run gate: $($_.Exception.Message)" "Fix check_active_run_gate.ps1."
}

try {
    $preflight = Invoke-JsonScript -Path $edgePreflightScript -Arguments @("-Json")
    if ([bool]$preflight.ok -and [int]$preflight.fail_count -eq 0) {
        Add-Check $checks "edge_preflight" "pass" "Preflight status=$($preflight.status); fail_count=0; warn_count=$($preflight.warn_count)."
    } else {
        Add-Check $checks "edge_preflight" "fail" "Preflight failed: status=$($preflight.status); fail_count=$($preflight.fail_count); warn_count=$($preflight.warn_count)." "Fix preflight before START72H."
    }
} catch {
    Add-Check $checks "edge_preflight" "fail" "Could not run edge preflight: $($_.Exception.Message)" "Fix trading_edge_preflight.ps1."
}

try {
    $nextGoal = Invoke-JsonScript -Path $nextGoalStepScript -Arguments @("-Json")
    if ([string]$nextGoal.decision -eq "SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT" -and [bool]$nextGoal.requires_user_approval_for_actual_collect) {
        Add-Check $checks "next_goal_step" "pass" "Next goal decision=$($nextGoal.decision); actual collect still requires explicit approval."
    } else {
        Add-Check $checks "next_goal_step" "fail" "Unexpected next goal decision=$($nextGoal.decision); requires_user_approval_for_actual_collect=$($nextGoal.requires_user_approval_for_actual_collect)." "Re-run/fix trading_next_goal_step.ps1."
    }
} catch {
    Add-Check $checks "next_goal_step" "fail" "Could not run next-goal step: $($_.Exception.Message)" "Fix trading_next_goal_step.ps1."
}

try {
    $goalStatus = Invoke-JsonScript -Path $goalStatusScript -Arguments @("-Json")
    if ([int]$goalStatus.accepted_trading_strategies -eq 0 -and [bool]$goalStatus.requires_user_approval_for_actual_collect) {
        Add-Check $checks "goal_status" "pass" "Goal status confirms accepted_trading_strategies=0 and approval is required for actual collect."
    } else {
        Add-Check $checks "goal_status" "fail" "Goal status mismatch: accepted=$($goalStatus.accepted_trading_strategies); requires_approval=$($goalStatus.requires_user_approval_for_actual_collect)." "Fix trading_goal_status.ps1."
    }
} catch {
    Add-Check $checks "goal_status" "fail" "Could not run goal status: $($_.Exception.Message)" "Fix trading_goal_status.ps1."
}

try {
    $readiness = Invoke-JsonScript -Path $readinessScript -Arguments @("-Json")
    if ([bool]$readiness.ok -and -not [bool]$readiness.would_start -and [string]$readiness.status -eq "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION") {
        Add-Check $checks "ws_collect_readiness" "pass" "Readiness is non-starting and status=$($readiness.status)."
    } else {
        Add-Check $checks "ws_collect_readiness" "fail" "Readiness mismatch: ok=$($readiness.ok); would_start=$($readiness.would_start); status=$($readiness.status)." "Fix readiness before START72H."
    }
} catch {
    Add-Check $checks "ws_collect_readiness" "fail" "Could not run readiness: $($_.Exception.Message)" "Fix trading_ws_collect_readiness.ps1."
}

try {
    $approvalContract = Invoke-JsonScript -Path $approvalContractScript -Arguments @("-Json")
    if ([bool]$approvalContract.ok -and [string]$approvalContract.status -eq "APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT") {
        Add-Check $checks "approval_contract" "pass" "Approval contract status=$($approvalContract.status); fail_count=0."
    } else {
        Add-Check $checks "approval_contract" "fail" "Approval contract mismatch: ok=$($approvalContract.ok); status=$($approvalContract.status); fail_count=$($approvalContract.fail_count)." "Fix approval contract before START72H."
    }
} catch {
    Add-Check $checks "approval_contract" "fail" "Could not run approval contract: $($_.Exception.Message)" "Fix trading_collect_approval_contract.ps1."
}

try {
    $swarmStatus = Invoke-JsonScript -Path $swarmStatusScript -Arguments @("-Json")
    if ([string]$swarmStatus.status -eq "SWARM_LIMITED" -and [bool]$swarmStatus.swarm_limited) {
        Add-Check $checks "swarm_status" "pass" "Swarm is limited; manual Codex fallback is active and this packet is not swarm approval."
    } elseif ([string]$swarmStatus.status -eq "SWARM_APPROVED") {
        Add-Check $checks "swarm_status" "pass" "Swarm status is approved."
    } else {
        Add-Check $checks "swarm_status" "warn" "Swarm status=$($swarmStatus.status); do not treat this as approval." "Retry swarm at the next major checkpoint if runtime is available."
    }
} catch {
    Add-Check $checks "swarm_status" "warn" "Could not read swarm status: $($_.Exception.Message)" "Continue manual Codex fallback; retry swarm later."
}

try {
    $testPlan = Invoke-JsonScript -Path $testRunnerScript -Arguments @("-PlanOnly", "-Json")
    if ([bool]$testPlan.ok -and [string]$testPlan.status -eq "READY" -and [string]$testPlan.selected_python -and [string]$testPlan.requests_version) {
        Add-Check $checks "test_runner_plan" "pass" "Test runner selected $($testPlan.selected_python) with requests=$($testPlan.requests_version)."
    } else {
        Add-Check $checks "test_runner_plan" "fail" "Test runner is not ready: status=$($testPlan.status); selected_python=$($testPlan.selected_python)." "Fix Python runtime before START72H."
    }
} catch {
    Add-Check $checks "test_runner_plan" "fail" "Could not run test runner PlanOnly: $($_.Exception.Message)" "Fix run_trading_tests.ps1."
}

try {
    $planPreview = Read-JsonFile -Path $planPreviewLatest
    if ([string]$planPreview.mode -eq "ws_collect_visible_plan" -and -not [bool]$planPreview.would_start -and [double]$planPreview.hours -eq 72.0) {
        Add-Check $checks "plan_preview" "pass" "Plan preview is 72h, non-starting, branch=$($planPreview.selected_branch)."
    } else {
        Add-Check $checks "plan_preview" "fail" "Plan preview mismatch: mode=$($planPreview.mode); would_start=$($planPreview.would_start); hours=$($planPreview.hours)." "Refresh PlanOnly preview before START72H."
    }
} catch {
    Add-Check $checks "plan_preview" "fail" "Could not read plan preview: $($_.Exception.Message)" "Run TRADING_PREVIEW_DENSE_WS.cmd."
}

$commandAfterApproval = ""
if ($gate -and (Has-Property $gate "command_after_explicit_approval")) {
    $commandAfterApproval = [string]$gate.command_after_explicit_approval
} elseif ($readiness -and (Has-Property $readiness "command_after_explicit_approval")) {
    $commandAfterApproval = [string]$readiness.command_after_explicit_approval
}
$commandIssues = [System.Collections.Generic.List[string]]::new()
foreach ($needle in @("start_ws_collect_visible.ps1", "-Hours 72", "-ConfirmedLongRun", "mexc,gateio", "no_binance_dense_ws_sweep_20260628.csv")) {
    if (-not (Test-CommandContains -Command $commandAfterApproval -Needle $needle)) {
        $commandIssues.Add("missing:$needle") | Out-Null
    }
}
foreach ($needle in @("-PlanOnly", "-Hours 6 -ConfirmedLongRun")) {
    if (Test-CommandContains -Command $commandAfterApproval -Needle $needle) {
        $commandIssues.Add("forbidden:$needle") | Out-Null
    }
}
if ($commandIssues.Count -eq 0) {
    Add-Check $checks "command_after_explicit_approval" "pass" "Actual start command is guarded 72h dense WS collect and is not PlanOnly."
} else {
    Add-Check $checks "command_after_explicit_approval" "fail" "Start command contract mismatch: $($commandIssues -join '; ')." "Fix command_after_explicit_approval before START72H."
}

$universePath = ""
if ($planPreview -and (Has-Property $planPreview "universe_path")) {
    $universePath = [string]$planPreview.universe_path
} elseif ($readiness -and (Has-Property $readiness "universe_path")) {
    $universePath = [string]$readiness.universe_path
}
$resolvedUniversePath = Resolve-RepoPath -Path $universePath
try {
    $universeRows = @(Import-Csv -LiteralPath $resolvedUniversePath)
    $uniqueSymbols = @($universeRows | ForEach-Object { ([string]$_.symbol).Trim().ToUpperInvariant() } | Where-Object { $_ } | Sort-Object -Unique)
    if ($universeRows.Count -ge 32 -and $uniqueSymbols.Count -ge 32) {
        Add-Check $checks "universe_coverage" "pass" "Universe rows=$($universeRows.Count); unique_symbols=$($uniqueSymbols.Count)."
    } else {
        Add-Check $checks "universe_coverage" "fail" "Universe too small: rows=$($universeRows.Count); unique_symbols=$($uniqueSymbols.Count)." "Regenerate dense universe."
    }
} catch {
    Add-Check $checks "universe_coverage" "fail" "Could not inspect universe path '$resolvedUniversePath': $($_.Exception.Message)" "Fix dense universe before START72H."
}

$fingerprintPaths = @(
    $resolvedUniversePath,
    $startWsCollectScript,
    $runMvpScript,
    $wsCollectorPy,
    $readinessScript,
    $approvalContractScript,
    $edgePreflightScript,
    $nextGoalStepScript,
    $goalStatusScript,
    $swarmStatusScript,
    $testRunnerScript,
    $postprocessScript,
    $replayValidationScript,
    $confirmedShortcut,
    $previewShortcut
)
$fingerprints = @($fingerprintPaths | ForEach-Object { Get-FileFingerprint -Path $_ })
$missingFingerprints = @($fingerprints | Where-Object { -not $_.exists })
if ($missingFingerprints.Count -eq 0) {
    Add-Check $checks "critical_file_fingerprints" "pass" "Captured SHA256 fingerprints for $($fingerprints.Count) critical files."
} else {
    Add-Check $checks "critical_file_fingerprints" "fail" "Missing critical files: $((@($missingFingerprints) | ForEach-Object { $_.path }) -join '; ')." "Restore missing files before START72H."
}

$failCount = @($checks | Where-Object { $_.status -eq "fail" }).Count
$warnCount = @($checks | Where-Object { $_.status -eq "warn" }).Count
$resolvedOutputPath = Resolve-RepoPath -Path $OutputPath
$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_ws_collect_approval_packet"
    ok = ($failCount -eq 0)
    status = if ($failCount -eq 0) { "READY_FOR_START72H_APPROVAL_PACKET" } else { "FAILED_START72H_APPROVAL_PACKET" }
    fail_count = $failCount
    warn_count = $warnCount
    research_only = $true
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    requires_explicit_user_approval_for_actual_collect = $true
    start_requires_exact_user_input = "START72H"
    gate = [ordered]@{
        status = if ($gate) { [string]$gate.status } else { "" }
        run_id = if ($gate) { [string]$gate.run_id } else { "" }
        replay_allowed = if ($gate -and (Has-Property $gate "replay_allowed")) { [bool]$gate.replay_allowed } else { $null }
        next_goal_decision = if ($gate -and (Has-Property $gate "next_goal_decision")) { [string]$gate.next_goal_decision } else { "" }
        rejected_postprocess_output = if ($gate -and $gate.output) { [string]$gate.output.path } else { "" }
        rejected_manifest_path = if ($gate -and (Has-Property $gate "manifest_path")) { [string]$gate.manifest_path } else { "" }
    }
    branch = [ordered]@{
        decision = if ($nextGoal) { [string]$nextGoal.decision } else { "" }
        selected_branch = if ($planPreview) { [string]$planPreview.selected_branch } else { "" }
        swarm_status = if ($swarmStatus) { [string]$swarmStatus.status } else { "UNKNOWN" }
        swarm_limited = [bool]($swarmStatus -and [bool]$swarmStatus.swarm_limited)
        accepted_trading_strategies = if ($goalStatus) { [int]$goalStatus.accepted_trading_strategies } else { 0 }
    }
    commands = [ordered]@{
        preview = if ($nextGoal) { [string]$nextGoal.primary_command } else { "" }
        command_after_explicit_approval = $commandAfterApproval
        postprocess_plan_after_collect = if ($planPreview) { [string]$planPreview.postprocess_plan_command_after_ready } else { "" }
        postprocess_after_collect = if ($planPreview) { [string]$planPreview.postprocess_command_after_ready } else { "" }
        replay_validation_plan_after_postprocess = if ($planPreview) { [string]$planPreview.replay_validation_plan_after_postprocess } else { "" }
        replay_validation_after_review = if ($planPreview) { [string]$planPreview.replay_validation_after_review } else { "" }
    }
    paths = [ordered]@{
        output_path = $resolvedOutputPath
        plan_preview_latest = $planPreviewLatest
        universe_path = $resolvedUniversePath
        readiness_output_path = if ($readiness -and (Has-Property $readiness "output_path")) { [string]$readiness.output_path } else { "" }
    }
    test_runner = [ordered]@{
        selected_python = if ($testPlan) { [string]$testPlan.selected_python } else { "" }
        requests_version = if ($testPlan) { [string]$testPlan.requests_version } else { "" }
        command = if ($testPlan) { [string]$testPlan.command } else { "" }
    }
    checks = @($checks)
    fingerprints = @($fingerprints)
}

$outputDir = Split-Path -Parent $resolvedOutputPath
if ($outputDir -and (-not (Test-Path -LiteralPath $outputDir))) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resolvedOutputPath -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "trading_mvp WS collect approval packet: $($result.status)" -ForegroundColor Cyan
    Write-Host "ok=$($result.ok); fails=$failCount; warnings=$warnCount"
    Write-Host "output=$resolvedOutputPath"
    foreach ($check in $checks) {
        $prefix = if ($check.status -eq "pass") { "[PASS]" } elseif ($check.status -eq "warn") { "[WARN]" } else { "[FAIL]" }
        Write-Host "$prefix $($check.name): $($check.evidence)"
        if ($check.action) {
            Write-Host "       Action: $($check.action)"
        }
    }
}

if ($failCount -gt 0) {
    exit 2
}
exit 0
