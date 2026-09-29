param(
    [switch]$Json,
    [string]$GatePath = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$guardArgs = @{ Json = $true }
if ($GatePath) { $guardArgs.GatePath = $GatePath }
$guard = (& (Join-Path $PSScriptRoot "check_trading_mvp_autopilot.ps1") @guardArgs | Out-String | ConvertFrom-Json)
$gateArgs = @{ Json = $true }
if ($GatePath) { $gateArgs.GatePath = $GatePath }
$gate = (& (Join-Path $PSScriptRoot "check_active_run_gate.ps1") @gateArgs | Out-String | ConvertFrom-Json)
$decision = [string]$guard.decision
$next = [string]$guard.next_action
$status = [string]$guard.status
# A changed live gate overrides even a freshly produced readiness snapshot.
if ($gate.gate_status -ne 'READY_FOR_POSTPROCESS' -and
    $gate.gate_status -ne $guard.gate.status -and $guard.status -notlike 'PAUSED_*') {
    $decision = if ($gate.gate_status -eq 'RUNNING') { 'MONITOR_ACTIVE_RUN' } else { 'CRITICAL_STOP_ACTIVE_RUN_GATE' }
    $next = 'inspect_active_run_without_starting_new_work'
    $status = if ($gate.gate_status -eq 'RUNNING') { 'RUNNING_MONITOR_ONLY' } else { 'CRITICAL_STOP' }
}
$result = [ordered]@{
    schema = 'trading_mvp_reconciled_goal_status_v1'
    project = 'trading_mvp'
    status = $status
    decision = $decision
    next_goal_decision = $decision
    next_allowed_action = $next
    primary_edge_status = 'NO_ACCEPTED_STRATEGY'
    selected_branch = 'premarket_forward_depth'
    gate_status = $gate.gate_status
    active_run_id = $gate.run_id
    gate_disposition = $gate.next_goal_decision
    readiness = $guard.current_sprint_readiness
    usage = $guard.usage
    stop_new_actions = $true
    collector_launch_authorized = $false
    evaluator_or_oos_authorized = $false
    replay_allowed = $false
    backtest_allowed = $false
    grid_allowed = $false
    paper_forward_allowed = $false
    network_launch_authorized = $false
    schedules_remain_paused = $true
    listing_momentum_scope = 'EXTERNAL_PROJECT_NO_PARENT_EXECUTION'
    primary_command = $null
    action_due = $false
}
if ($Json) { $result | ConvertTo-Json -Depth 40; return }
Write-Host "Research checkpoint: $decision"
Write-Host "Active gate: $($gate.gate_status) / $($gate.run_id)"
Write-Host "Next: $next"
Write-Host 'Offline-only checkpoint; no launches; paused schedules unchanged.'
