param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$nextGoalStep = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$goalStatusScript = Join-Path $repoRoot "tools\trading_goal_status.ps1"
$branchSelectorScript = Join-Path $repoRoot "tools\trading_branch_selector.ps1"
$readinessDefaultPath = Join-Path $repoRoot "exports\trading-mvp\analysis\trading_ws_collect_readiness_current.json"
$confirmedShortcut = Join-Path $repoRoot "TRADING_START_DENSE_WS_CONFIRMED.cmd"

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
        [string]$Path
    )
    $output = & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -Json 2>&1
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

function Test-CommandHas {
    param(
        [string]$Command,
        [string]$Needle
    )
    return (-not [string]::IsNullOrWhiteSpace($Command) -and $Command -match [regex]::Escape($Needle))
}

function Test-CommandDoesNotHave {
    param(
        [string]$Command,
        [string]$Needle
    )
    return ([string]::IsNullOrWhiteSpace($Command) -or $Command -notmatch [regex]::Escape($Needle))
}

function Add-Command-Check {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Name,
        [string]$Command,
        [string[]]$MustContain,
        [string[]]$MustNotContain,
        [string]$Evidence
    )
    $issues = [System.Collections.Generic.List[string]]::new()
    foreach ($needle in $MustContain) {
        if (-not (Test-CommandHas -Command $Command -Needle $needle)) {
            $issues.Add("missing:$needle") | Out-Null
        }
    }
    foreach ($needle in $MustNotContain) {
        if (-not (Test-CommandDoesNotHave -Command $Command -Needle $needle)) {
            $issues.Add("forbidden:$needle") | Out-Null
        }
    }
    if ($issues.Count -eq 0) {
        Add-Check $Checks $Name "pass" $Evidence
    } else {
        Add-Check $Checks $Name "fail" "$Evidence Issues: $($issues -join ', ')." "Fix the command contract before any confirmed visible collect."
    }
}

$checks = [System.Collections.Generic.List[object]]::new()

$gate = $null
$nextGoal = $null
$goalStatus = $null
$branch = $null
$readiness = $null

try {
    $gate = Invoke-JsonScript -Path $gateChecker
    Add-Check $checks "gate_readback" "pass" "Gate readback status=$($gate.status); run_id=$($gate.run_id)."
} catch {
    Add-Check $checks "gate_readback" "fail" "Could not read active run gate: $($_.Exception.Message)" "Fix active-run gate before continuing."
}

try {
    $nextGoal = Invoke-JsonScript -Path $nextGoalStep
    Add-Check $checks "next_goal_readback" "pass" "Next-goal readback decision=$($nextGoal.decision)."
} catch {
    Add-Check $checks "next_goal_readback" "fail" "Could not read next-goal step: $($_.Exception.Message)" "Fix tools/trading_next_goal_step.ps1."
}

try {
    $goalStatus = Invoke-JsonScript -Path $goalStatusScript
    Add-Check $checks "goal_status_readback" "pass" "Goal-status readback gate_status=$($goalStatus.gate_status)."
} catch {
    Add-Check $checks "goal_status_readback" "fail" "Could not read goal status: $($_.Exception.Message)" "Fix tools/trading_goal_status.ps1."
}

try {
    $branch = Invoke-JsonScript -Path $branchSelectorScript
    Add-Check $checks "branch_selector_readback" "pass" "Branch-selector readback decision=$($branch.decision)."
} catch {
    Add-Check $checks "branch_selector_readback" "fail" "Could not read branch selector: $($_.Exception.Message)" "Fix tools/trading_branch_selector.ps1."
}

$readinessPath = $readinessDefaultPath
if ($gate -and (Has-Property $gate "readiness_output_path") -and -not [string]::IsNullOrWhiteSpace([string]$gate.readiness_output_path)) {
    $readinessPath = [string]$gate.readiness_output_path
}
try {
    $readiness = Read-JsonFile -Path $readinessPath
    Add-Check $checks "readiness_artifact_readback" "pass" "Readiness artifact read: $readinessPath."
} catch {
    Add-Check $checks "readiness_artifact_readback" "fail" "Could not read readiness artifact: $($_.Exception.Message)" "Run trading_ws_collect_readiness.ps1 -Json before requesting START72H."
}

$applicable = $false
if ($gate) {
    $replayAllowedValue = if (Has-Property $gate "replay_allowed") { [bool]$gate.replay_allowed } else { $true }
    $nextDecision = if (Has-Property $gate "next_goal_decision") { [string]$gate.next_goal_decision } else { "" }
    $applicable = ((-not $replayAllowedValue) -or $nextDecision -eq "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL")
}

if (-not $applicable) {
    Add-Check $checks "approval_contract_applicability" "pass" "Current gate does not expose a rejected replay_allowed=false artifact that requires a new visible 72h collect; approval contract is not currently gating an actual start."
} else {
    Add-Check $checks "approval_contract_applicability" "pass" "Current rejected artifact requires a new visible 72h WS collect only after explicit user approval."

    $gateIssues = [System.Collections.Generic.List[string]]::new()
    if ([string]$gate.status -notin @("READY_FOR_POSTPROCESS", "READY_FOR_EDGE_PROOF_STEP")) { $gateIssues.Add("status=$($gate.status)") | Out-Null }
    if ((Has-Property $gate "replay_allowed") -and [bool]$gate.replay_allowed) { $gateIssues.Add("replay_allowed=true") | Out-Null }
    if (-not [bool]$gate.requires_explicit_user_approval_for_actual_collect) { $gateIssues.Add("requires_explicit_user_approval_for_actual_collect=false") | Out-Null }
    if ([string]$gate.next_goal_decision -ne "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL") { $gateIssues.Add("next_goal_decision=$($gate.next_goal_decision)") | Out-Null }
    if ($gateIssues.Count -eq 0) {
        Add-Check $checks "gate_rejected_artifact_contract" "pass" "Gate blocks replay/grid on rejected ws-postprocess and requires explicit approval for the next actual collect."
    } else {
        Add-Check $checks "gate_rejected_artifact_contract" "fail" "Gate approval contract mismatch: $($gateIssues -join '; ')." "Do not start collect until gate readback is corrected."
    }

    Add-Command-Check $checks "gate_actual_collect_command" ([string]$gate.command_after_explicit_approval) `
        @("-Hours 72", "-ConfirmedLongRun", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
        @("-PlanOnly", "-Hours 6 -ConfirmedLongRun") `
        "Gate actual collect command is the guarded 72h dense WS command."

    $nextIssues = [System.Collections.Generic.List[string]]::new()
    if (-not $nextGoal) {
        $nextIssues.Add("missing_next_goal") | Out-Null
    } else {
        if ([bool]$nextGoal.requires_user_approval) { $nextIssues.Add("requires_user_approval=true_for_plan_step") | Out-Null }
        if (-not [bool]$nextGoal.requires_user_approval_for_actual_collect) { $nextIssues.Add("requires_user_approval_for_actual_collect=false") | Out-Null }
    }
    if ($nextIssues.Count -eq 0) {
        Add-Check $checks "next_goal_approval_contract" "pass" "Next-goal permits only non-starting PlanOnly work before explicit approval for actual collect."
    } else {
        Add-Check $checks "next_goal_approval_contract" "fail" "Next-goal approval contract mismatch: $($nextIssues -join '; ')." "Fix trading_next_goal_step.ps1 before showing a start path."
    }
    if ($nextGoal) {
        Add-Command-Check $checks "next_goal_primary_preview_command" ([string]$nextGoal.primary_command) `
            @("-Hours 72", "-PlanOnly", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-ConfirmedLongRun", "-Hours 6 -ConfirmedLongRun") `
            "Next-goal primary command is a non-starting dense WS preview."
        Add-Command-Check $checks "next_goal_actual_collect_command" ([string]$nextGoal.commands.visible_ws_collect_after_approval) `
            @("-Hours 72", "-ConfirmedLongRun", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-PlanOnly", "-Hours 6 -ConfirmedLongRun") `
            "Next-goal actual command remains gated behind explicit approval."
    }

    $statusIssues = [System.Collections.Generic.List[string]]::new()
    if (-not $goalStatus) {
        $statusIssues.Add("missing_goal_status") | Out-Null
    } else {
        if (-not [bool]$goalStatus.visible_ws_collect_requires_user_approval) { $statusIssues.Add("visible_ws_collect_requires_user_approval=false") | Out-Null }
        if (-not [bool]$goalStatus.requires_user_approval_for_actual_collect) { $statusIssues.Add("requires_user_approval_for_actual_collect=false") | Out-Null }
        if ([bool]$goalStatus.live_orders) { $statusIssues.Add("live_orders=true") | Out-Null }
    }
    if ($statusIssues.Count -eq 0) {
        Add-Check $checks "goal_status_approval_contract" "pass" "Goal status exposes explicit user approval as required for actual WS collect and keeps live trading blocked."
    } else {
        Add-Check $checks "goal_status_approval_contract" "fail" "Goal-status approval contract mismatch: $($statusIssues -join '; ')." "Fix trading_goal_status.ps1 readback."
    }
    if ($goalStatus) {
        Add-Command-Check $checks "goal_status_preview_command" ([string]$goalStatus.visible_ws_collect_preview_command) `
            @("-Hours 72", "-PlanOnly", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-ConfirmedLongRun", "-Hours 6 -ConfirmedLongRun") `
            "Goal status preview command is non-starting."
        Add-Command-Check $checks "goal_status_actual_collect_command" ([string]$goalStatus.visible_ws_collect_command) `
            @("-Hours 72", "-ConfirmedLongRun", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-PlanOnly", "-Hours 6 -ConfirmedLongRun") `
            "Goal status actual collect command is guarded."
    }

    $branchIssues = [System.Collections.Generic.List[string]]::new()
    if (-not $branch) {
        $branchIssues.Add("missing_branch_selector") | Out-Null
    } else {
        if (-not [bool]$branch.requires_user_approval_for_actual_collect) { $branchIssues.Add("requires_user_approval_for_actual_collect=false") | Out-Null }
        if (-not [bool]$branch.artifacts.visible_ws_collect_requires_user_approval) { $branchIssues.Add("artifacts.visible_ws_collect_requires_user_approval=false") | Out-Null }
        if ([bool]$branch.live_orders) { $branchIssues.Add("live_orders=true") | Out-Null }
    }
    if ($branchIssues.Count -eq 0) {
        Add-Check $checks "branch_selector_approval_contract" "pass" "Branch selector keeps actual collect user-approved and live trading blocked."
    } else {
        Add-Check $checks "branch_selector_approval_contract" "fail" "Branch selector approval contract mismatch: $($branchIssues -join '; ')." "Fix trading_branch_selector.ps1 artifacts."
    }
    if ($branch) {
        Add-Command-Check $checks "branch_selector_preview_command" ([string]$branch.artifacts.visible_ws_collect_plan) `
            @("-Hours 72", "-PlanOnly", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-ConfirmedLongRun", "-Hours 6 -ConfirmedLongRun") `
            "Branch selector preview command is non-starting."
        Add-Command-Check $checks "branch_selector_actual_collect_command" ([string]$branch.artifacts.visible_ws_collect_after_approval) `
            @("-Hours 72", "-ConfirmedLongRun", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-PlanOnly", "-Hours 6 -ConfirmedLongRun") `
            "Branch selector actual command is guarded."
    }

    $readinessIssues = [System.Collections.Generic.List[string]]::new()
    if (-not $readiness) {
        $readinessIssues.Add("missing_readiness") | Out-Null
    } else {
        if (-not [bool]$readiness.ok) { $readinessIssues.Add("ok=false") | Out-Null }
        if ([bool]$readiness.would_start) { $readinessIssues.Add("would_start=true") | Out-Null }
        if (-not [bool]$readiness.requires_explicit_user_approval_for_actual_collect) { $readinessIssues.Add("requires_explicit_user_approval_for_actual_collect=false") | Out-Null }
        if ([bool]$readiness.live_orders) { $readinessIssues.Add("live_orders=true") | Out-Null }
        if ([bool]$readiness.api_keys) { $readinessIssues.Add("api_keys=true") | Out-Null }
        if ([bool]$readiness.leverage_or_margin) { $readinessIssues.Add("leverage_or_margin=true") | Out-Null }
        if ([string]$readiness.status -ne "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION") { $readinessIssues.Add("status=$($readiness.status)") | Out-Null }
    }
    if ($readinessIssues.Count -eq 0) {
        Add-Check $checks "readiness_approval_contract" "pass" "Readiness artifact is non-starting, research-only and requires explicit approval for actual collect."
    } else {
        Add-Check $checks "readiness_approval_contract" "fail" "Readiness approval contract mismatch: $($readinessIssues -join '; ')." "Refresh/fix trading_ws_collect_readiness.ps1 before asking for START72H."
    }
    if ($readiness) {
        Add-Command-Check $checks "readiness_actual_collect_command" ([string]$readiness.command_after_explicit_approval) `
            @("-Hours 72", "-ConfirmedLongRun", "start_ws_collect_visible.ps1", "no_binance_dense_ws_sweep_20260628.csv") `
            @("-PlanOnly", "-Hours 6 -ConfirmedLongRun") `
            "Readiness actual command is guarded."
    }

    if (Test-Path -LiteralPath $confirmedShortcut) {
        $shortcutText = Get-Content -Raw -LiteralPath $confirmedShortcut
        $shortcutIssues = [System.Collections.Generic.List[string]]::new()
        foreach ($needle in @("START72H", "trading_ws_collect_readiness.ps1", "trading_collect_approval_contract.ps1", "-Hours 72", "-ConfirmedLongRun", "no_binance_dense_ws_sweep_20260628.csv")) {
            if ($shortcutText -notmatch [regex]::Escape($needle)) {
                $shortcutIssues.Add("missing:$needle") | Out-Null
            }
        }
        if ($shortcutText -match [regex]::Escape("-Hours 6 -ConfirmedLongRun")) {
            $shortcutIssues.Add("forbidden:-Hours 6 -ConfirmedLongRun") | Out-Null
        }
        if ($shortcutIssues.Count -eq 0) {
            Add-Check $checks "confirmed_shortcut_start72h_contract" "pass" "Confirmed shortcut requires START72H, runs readiness plus approval contract, and uses guarded 72h dense WS command."
        } else {
            Add-Check $checks "confirmed_shortcut_start72h_contract" "fail" "Confirmed shortcut contract mismatch: $($shortcutIssues -join '; ')." "Fix TRADING_START_DENSE_WS_CONFIRMED.cmd."
        }
    } else {
        Add-Check $checks "confirmed_shortcut_start72h_contract" "fail" "Missing confirmed shortcut: $confirmedShortcut." "Restore TRADING_START_DENSE_WS_CONFIRMED.cmd."
    }
}

$failCount = @($checks | Where-Object { $_.status -eq "fail" }).Count
$warnCount = @($checks | Where-Object { $_.status -eq "warn" }).Count

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_collect_approval_contract"
    ok = ($failCount -eq 0)
    status = if ($failCount -gt 0) { "FAILED_APPROVAL_CONTRACT" } elseif ($applicable) { "APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT" } else { "NOT_APPLICABLE_CURRENT_ARTIFACT_ACCEPTED_OR_OTHER_BRANCH" }
    applicable = $applicable
    fail_count = $failCount
    warn_count = $warnCount
    checks = @($checks)
    gate_status = if ($gate) { [string]$gate.status } else { $null }
    gate_replay_allowed = if ($gate -and (Has-Property $gate "replay_allowed")) { [bool]$gate.replay_allowed } else { $null }
    next_goal_decision = if ($gate -and (Has-Property $gate "next_goal_decision")) { [string]$gate.next_goal_decision } else { $null }
    requires_explicit_user_approval_for_actual_collect = if ($gate -and (Has-Property $gate "requires_explicit_user_approval_for_actual_collect")) { [bool]$gate.requires_explicit_user_approval_for_actual_collect } else { $null }
    preview_command = if ($nextGoal) { [string]$nextGoal.primary_command } else { $null }
    command_after_explicit_approval = if ($gate -and (Has-Property $gate "command_after_explicit_approval")) { [string]$gate.command_after_explicit_approval } else { $null }
    readiness_path = $readinessPath
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host "trading_mvp collect approval contract" -ForegroundColor Cyan
    Write-Host "Status: $($result.status)"
    Write-Host "Failures: $failCount; Warnings: $warnCount"
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
