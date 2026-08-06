param(
    [string]$OutputPath = "exports\trading-mvp\analysis\listing_event_history_collect_approval_packet_current.json",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$nextGoalStepScript = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$goalStatusScript = Join-Path $repoRoot "tools\trading_goal_status.ps1"
$branchSelectorScript = Join-Path $repoRoot "tools\trading_branch_selector.ps1"
$previewScript = Join-Path $repoRoot "tools\trading_listing_event_history_collect_preview.ps1"
$previewModule = Join-Path $repoRoot "trading_mvp\src\listing_event_history_collect_plan.py"
$normalizerModule = Join-Path $repoRoot "trading_mvp\src\listing_event_normalizer.py"
$currentGoalPlan = Join-Path $repoRoot "docs\plans\2026-07-08-trading-mvp-current-goal.md"
$calendarPath = Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.csv"

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

function Resolve-PreviewPath {
    param($Gate)
    if ($Gate -and (Has-Property $Gate "last_listing_event_history_collect_preview_output_path")) {
        $candidate = [string]$Gate.last_listing_event_history_collect_preview_output_path
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $latest = Get-ChildItem -LiteralPath (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "listing_event_history_collect_preview_*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        return $latest.FullName
    }
    return ""
}

$checks = [System.Collections.Generic.List[object]]::new()
$gate = $null
$nextGoal = $null
$goalStatus = $null
$branch = $null
$preview = $null

try {
    $gate = Invoke-JsonScript -Path $gateChecker -Arguments @("-Json")
    if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        Add-Check $checks "active_run_gate" "fail" "Gate status=$($gate.status); only status/resume handling is allowed." "Do not request or start listing-event history collect."
    } else {
        Add-Check $checks "active_run_gate" "pass" "Gate status=$($gate.status); run_id=$($gate.run_id)."
    }
} catch {
    Add-Check $checks "active_run_gate" "fail" "Could not read active-run gate: $($_.Exception.Message)" "Fix check_active_run_gate.ps1."
}

try {
    $nextGoal = Invoke-JsonScript -Path $nextGoalStepScript -Arguments @("-Json")
    Add-Check $checks "next_goal_readback" "pass" "Next-goal decision=$($nextGoal.decision)."
} catch {
    Add-Check $checks "next_goal_readback" "fail" "Could not read next-goal step: $($_.Exception.Message)" "Fix trading_next_goal_step.ps1."
}

try {
    $goalStatus = Invoke-JsonScript -Path $goalStatusScript -Arguments @("-Json")
    Add-Check $checks "goal_status_readback" "pass" "Goal-status primary_edge_status=$($goalStatus.primary_edge_status)."
} catch {
    Add-Check $checks "goal_status_readback" "fail" "Could not read goal status: $($_.Exception.Message)" "Fix trading_goal_status.ps1."
}

try {
    $branch = Invoke-JsonScript -Path $branchSelectorScript -Arguments @("-Json")
    Add-Check $checks "branch_selector_readback" "pass" "Branch selector decision=$($branch.decision)."
} catch {
    Add-Check $checks "branch_selector_readback" "fail" "Could not read branch selector: $($_.Exception.Message)" "Fix trading_branch_selector.ps1."
}

$previewPath = Resolve-PreviewPath -Gate $gate
try {
    if ([string]::IsNullOrWhiteSpace($previewPath)) {
        throw "No listing_event_history_collect_preview_*.json artifact found."
    }
    $preview = Read-JsonFile -Path $previewPath
    Add-Check $checks "preview_artifact_readback" "pass" "Preview artifact read: $previewPath."
} catch {
    Add-Check $checks "preview_artifact_readback" "fail" "Could not read preview artifact: $($_.Exception.Message)" "Run trading_listing_event_history_collect_preview.ps1 -UpdateGate -Json before approval."
}

if ($gate) {
    $gateIssues = [System.Collections.Generic.List[string]]::new()
    if ([string]$gate.status -ne "READY_FOR_POSTPROCESS") { $gateIssues.Add("status=$($gate.status)") | Out-Null }
    if ([string]$gate.next_goal_decision -ne "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL") { $gateIssues.Add("next_goal_decision=$($gate.next_goal_decision)") | Out-Null }
    if ((Has-Property $gate "replay_allowed") -and [bool]$gate.replay_allowed) { $gateIssues.Add("replay_allowed=true") | Out-Null }
    if (-not [bool]$gate.requires_explicit_user_approval_for_actual_collect) { $gateIssues.Add("requires_explicit_user_approval_for_actual_collect=false") | Out-Null }
    if (-not [string]::IsNullOrWhiteSpace([string]$gate.command_after_explicit_approval)) { $gateIssues.Add("command_after_explicit_approval_not_empty") | Out-Null }
    if ($gateIssues.Count -eq 0) {
        Add-Check $checks "gate_listing_history_contract" "pass" "Gate blocks replay/grid and requires explicit approval before actual listing-event history collect."
    } else {
        Add-Check $checks "gate_listing_history_contract" "fail" "Gate contract mismatch: $($gateIssues -join '; ')." "Do not start collect until active-run gate is corrected."
    }
}

if ($nextGoal) {
    $nextIssues = [System.Collections.Generic.List[string]]::new()
    if ([string]$nextGoal.decision -ne "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL") { $nextIssues.Add("decision=$($nextGoal.decision)") | Out-Null }
    if (-not [bool]$nextGoal.requires_user_approval) { $nextIssues.Add("requires_user_approval=false") | Out-Null }
    if (-not [bool]$nextGoal.requires_user_approval_for_actual_collect) { $nextIssues.Add("requires_user_approval_for_actual_collect=false") | Out-Null }
    if ([string]$nextGoal.primary_command -notmatch "await explicit user approval") { $nextIssues.Add("primary_command_not_awaiting_approval") | Out-Null }
    if ($nextIssues.Count -eq 0) {
        Add-Check $checks "next_goal_listing_history_contract" "pass" "Next-goal controller exposes awaiting-approval state, not a start command."
    } else {
        Add-Check $checks "next_goal_listing_history_contract" "fail" "Next-goal contract mismatch: $($nextIssues -join '; ')." "Fix trading_next_goal_step.ps1 before requesting approval."
    }
}

if ($goalStatus) {
    $statusIssues = [System.Collections.Generic.List[string]]::new()
    if ([string]$goalStatus.primary_edge_status -ne "listing_event_history_collect_preview_awaiting_explicit_approval") { $statusIssues.Add("primary_edge_status=$($goalStatus.primary_edge_status)") | Out-Null }
    if (-not [bool]$goalStatus.requires_user_approval_for_actual_collect) { $statusIssues.Add("requires_user_approval_for_actual_collect=false") | Out-Null }
    if ($statusIssues.Count -eq 0) {
        Add-Check $checks "goal_status_listing_history_contract" "pass" "Goal status points to listing-event history approval, not replay/grid."
    } else {
        Add-Check $checks "goal_status_listing_history_contract" "fail" "Goal status contract mismatch: $($statusIssues -join '; ')." "Fix trading_goal_status.ps1."
    }
}

if ($branch) {
    $branchIssues = [System.Collections.Generic.List[string]]::new()
    if ([string]$branch.decision -ne "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL") { $branchIssues.Add("decision=$($branch.decision)") | Out-Null }
    if (-not [bool]$branch.requires_user_approval_for_actual_collect) { $branchIssues.Add("requires_user_approval_for_actual_collect=false") | Out-Null }
    if ([bool]$branch.live_orders) { $branchIssues.Add("live_orders=true") | Out-Null }
    if ($branchIssues.Count -eq 0) {
        Add-Check $checks "branch_selector_listing_history_contract" "pass" "Branch selector keeps actual collect behind explicit approval and live blocked."
    } else {
        Add-Check $checks "branch_selector_listing_history_contract" "fail" "Branch selector contract mismatch: $($branchIssues -join '; ')." "Fix trading_branch_selector.ps1."
    }
}

if ($preview) {
    $previewIssues = [System.Collections.Generic.List[string]]::new()
    $eventPlanSource = if ($preview.selection -and (Has-Property $preview.selection "event_plan_source")) { [string]$preview.selection.event_plan_source } else { "" }
    $availabilityDriven = (
        $eventPlanSource -eq "explicit_sample_events" -and
        $preview.availability_preflight -and
        [bool]$preview.availability_preflight.accepted
    )
    if ([string]$preview.decision -ne "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL") { $previewIssues.Add("decision=$($preview.decision)") | Out-Null }
    if ([bool]$preview.would_start) { $previewIssues.Add("would_start=true") | Out-Null }
    if ([bool]$preview.collect_allowed_now) { $previewIssues.Add("collect_allowed_now=true") | Out-Null }
    if (-not [bool]$preview.actual_collect_requires_explicit_user_approval) { $previewIssues.Add("actual_collect_requires_explicit_user_approval=false") | Out-Null }
    if (-not [bool]$preview.visible_terminal_or_monitor_required) { $previewIssues.Add("visible_terminal_or_monitor_required=false") | Out-Null }
    if ([bool]$preview.hidden_background_collect_allowed) { $previewIssues.Add("hidden_background_collect_allowed=true") | Out-Null }
    if ([bool]$preview.replay_allowed_now) { $previewIssues.Add("replay_allowed_now=true") | Out-Null }
    if ([bool]$preview.grid_allowed_now) { $previewIssues.Add("grid_allowed_now=true") | Out-Null }
    if ([bool]$preview.paper_forward_allowed) { $previewIssues.Add("paper_forward_allowed=true") | Out-Null }
    if ($availabilityDriven) {
        if ([int]$preview.selection.selected_events -lt 2) { $previewIssues.Add("availability_selected_events=$($preview.selection.selected_events)") | Out-Null }
        if ([int]$preview.selection.selected_unique_bases -lt 2) { $previewIssues.Add("availability_selected_unique_bases=$($preview.selection.selected_unique_bases)") | Out-Null }
        if (-not $preview.selection.sample_events -or @($preview.selection.sample_events).Count -ne [int]$preview.selection.selected_events) {
            $previewIssues.Add("availability_sample_events_not_full_event_plan") | Out-Null
        }
    } else {
        if ([int]$preview.selection.selected_events -lt 100) { $previewIssues.Add("selected_events=$($preview.selection.selected_events)") | Out-Null }
        if ([int]$preview.selection.selected_unique_bases -lt 30) { $previewIssues.Add("selected_unique_bases=$($preview.selection.selected_unique_bases)") | Out-Null }
        if ([int]$preview.selection.selected_nontradable_or_delisted_events -lt 1) { $previewIssues.Add("selected_nontradable_or_delisted_events=$($preview.selection.selected_nontradable_or_delisted_events)") | Out-Null }
    }
    if ([int]$preview.selection.selected_exchange_count -lt 2) { $previewIssues.Add("selected_exchange_count=$($preview.selection.selected_exchange_count)") | Out-Null }
    if ([int]$preview.request_budget.estimated_total_requests -lt 1) { $previewIssues.Add("estimated_total_requests=$($preview.request_budget.estimated_total_requests)") | Out-Null }
    foreach ($property in @("output_jsonl", "manifest_path", "event_plan_path", "stdout_path", "stderr_path")) {
        if (-not (Has-Property $preview.expected_outputs $property) -or [string]::IsNullOrWhiteSpace([string]$preview.expected_outputs.$property)) {
            $previewIssues.Add("missing_expected_output:$property") | Out-Null
        }
    }
    if ($previewIssues.Count -eq 0) {
        Add-Check $checks "preview_selection_contract" "pass" "Preview selected $($preview.selection.selected_events) events, $($preview.selection.selected_unique_bases) bases, $($preview.selection.selected_exchange_count) exchanges; collect remains non-starting."
    } else {
        Add-Check $checks "preview_selection_contract" "fail" "Preview contract mismatch: $($previewIssues -join '; ')." "Refresh/fix preview before requesting approval."
    }
}

if (Test-Path -LiteralPath $calendarPath) {
    $calendarRows = @(Import-Csv -LiteralPath $calendarPath)
    $delistedRows = @($calendarRows | Where-Object { [string]$_.is_delisted -eq "true" -or [string]$_.survivorship_status -eq "current_non_tradable_snapshot" })
    if ($calendarRows.Count -ge 1000 -and $delistedRows.Count -gt 0) {
        Add-Check $checks "calendar_survivorship_contract" "pass" "Calendar rows=$($calendarRows.Count); delisted/non-tradable rows=$($delistedRows.Count)."
    } else {
        Add-Check $checks "calendar_survivorship_contract" "fail" "Calendar lacks sufficient survivorship coverage: rows=$($calendarRows.Count); delisted/non-tradable=$($delistedRows.Count)." "Rebuild listing calendar before approval."
    }
} else {
    Add-Check $checks "calendar_survivorship_contract" "fail" "Missing calendar: $calendarPath." "Build listing event calendar before approval."
}

$fingerprintPaths = @(
    $gateChecker,
    $nextGoalStepScript,
    $goalStatusScript,
    $branchSelectorScript,
    $previewScript,
    $previewModule,
    $normalizerModule,
    $currentGoalPlan,
    $calendarPath,
    $previewPath
)
$fingerprints = @($fingerprintPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { Get-FileFingerprint -Path $_ })
$missingFingerprints = @($fingerprints | Where-Object { -not $_.exists })
if ($missingFingerprints.Count -eq 0) {
    Add-Check $checks "critical_file_fingerprints" "pass" "Captured SHA256 fingerprints for $($fingerprints.Count) listing-history approval files."
} else {
    Add-Check $checks "critical_file_fingerprints" "fail" "Missing critical files: $((@($missingFingerprints) | ForEach-Object { $_.path }) -join '; ')." "Restore missing files before approval."
}

$failCount = @($checks | Where-Object { $_.status -eq "fail" }).Count
$warnCount = @($checks | Where-Object { $_.status -eq "warn" }).Count
$resolvedOutputPath = Resolve-RepoPath -Path $OutputPath
$requiredUserInput = "подтверждаю visible listing-event OHLCV history collect"

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_listing_event_history_collect_approval_packet"
    ok = ($failCount -eq 0)
    status = if ($failCount -eq 0) { "READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET" } else { "FAILED_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET" }
    fail_count = $failCount
    warn_count = $warnCount
    research_only = $true
    would_start = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    requires_explicit_user_approval_for_actual_collect = $true
    start_requires_exact_user_input = $requiredUserInput
    approved_action_scope = "visible public OHLCV history collect implementation/run for listing events only; no replay/grid/live/API keys/paper-forward"
    gate = [ordered]@{
        status = if ($gate) { [string]$gate.status } else { "" }
        run_id = if ($gate) { [string]$gate.run_id } else { "" }
        replay_allowed = if ($gate -and (Has-Property $gate "replay_allowed")) { [bool]$gate.replay_allowed } else { $null }
        next_goal_decision = if ($gate -and (Has-Property $gate "next_goal_decision")) { [string]$gate.next_goal_decision } else { "" }
        requires_explicit_user_approval_for_actual_collect = if ($gate -and (Has-Property $gate "requires_explicit_user_approval_for_actual_collect")) { [bool]$gate.requires_explicit_user_approval_for_actual_collect } else { $null }
    }
    preview = [ordered]@{
        path = $previewPath
        decision = if ($preview) { [string]$preview.decision } else { "" }
        run_id = if ($preview) { [string]$preview.run_id } else { "" }
        selected_events = if ($preview) { [int]$preview.selection.selected_events } else { 0 }
        selected_unique_bases = if ($preview) { [int]$preview.selection.selected_unique_bases } else { 0 }
        selected_exchange_count = if ($preview) { [int]$preview.selection.selected_exchange_count } else { 0 }
        selected_nontradable_or_delisted_events = if ($preview) { [int]$preview.selection.selected_nontradable_or_delisted_events } else { 0 }
        estimated_total_requests = if ($preview) { [int]$preview.request_budget.estimated_total_requests } else { 0 }
        estimated_runtime_min = if ($preview) { [double]$preview.request_budget.estimated_runtime_min } else { 0.0 }
        expected_outputs = if ($preview) { $preview.expected_outputs } else { $null }
    }
    next_goal = [ordered]@{
        decision = if ($nextGoal) { [string]$nextGoal.decision } else { "" }
        primary_command = if ($nextGoal) { [string]$nextGoal.primary_command } else { "" }
    }
    paths = [ordered]@{
        output_path = $resolvedOutputPath
        calendar_path = $calendarPath
        current_goal_plan = $currentGoalPlan
    }
    checks = @($checks)
    fingerprints = @($fingerprints)
}

$outputDir = Split-Path -Parent $resolvedOutputPath
if ($outputDir -and (-not (Test-Path -LiteralPath $outputDir))) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resolvedOutputPath -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 12
} else {
    Write-Host "trading_mvp listing-event history collect approval packet: $($result.status)" -ForegroundColor Cyan
    Write-Host "ok=$($result.ok); fails=$failCount; warnings=$warnCount"
    Write-Host "required_user_input=$requiredUserInput"
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
