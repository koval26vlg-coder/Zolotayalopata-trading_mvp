param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [switch]$RejectIncomplete,
    [string]$Reason = "Explicitly rejected as incomplete; preserve for diagnostics only.",
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [string]$PointerPath = "",
    [string]$ArchiveDir = "",
    [string]$NextGoalDecision = "FAST_FIRST_EDGE_LAB_IMPLEMENTATION_ALLOWED",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $tempPath = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tempPath -Encoding utf8
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )

    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Get-LiveProcessIds {
    param([object[]]$Values)

    $live = @()
    foreach ($value in @($Values)) {
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { continue }
        $parsed = 0
        if (-not [int]::TryParse([string]$value, [ref]$parsed)) { continue }
        if (Get-Process -Id $parsed -ErrorAction SilentlyContinue) {
            $live += $parsed
        }
    }
    return @($live | Sort-Object -Unique)
}

if (-not $RejectIncomplete) {
    throw "Only explicit -RejectIncomplete resolution is supported."
}
if (-not (Test-Path -LiteralPath $GatePath)) {
    throw "Active run gate not found: $GatePath"
}

$gatePathResolved = (Resolve-Path -LiteralPath $GatePath).Path
$agentLogDir = Split-Path -Parent $gatePathResolved
if (-not $PointerPath) {
    $PointerPath = Join-Path $agentLogDir "current-run.json"
}
if (-not $ArchiveDir) {
    $ArchiveDir = Join-Path $agentLogDir "archived-gates"
}

$gate = Get-Content -Raw -LiteralPath $gatePathResolved | ConvertFrom-Json
$pointer = if (Test-Path -LiteralPath $PointerPath) {
    Get-Content -Raw -LiteralPath $PointerPath | ConvertFrom-Json
} else {
    $null
}

if ([string]$gate.run_id -ne $RunId) {
    throw "Gate run_id mismatch: expected '$RunId', found '$($gate.run_id)'."
}
if ($pointer -and [string]$pointer.run_id -ne $RunId) {
    throw "Pointer run_id mismatch: expected '$RunId', found '$($pointer.run_id)'."
}
$gateStatus = [string]$(if ($gate.PSObject.Properties.Name -contains "gate_status") { $gate.gate_status } else { $gate.status })
$pointerStatus = if ($pointer) { [string]$pointer.status } else { "" }
if ($gateStatus -ne "STOPPED_INCOMPLETE" -and $pointerStatus -ne "STOPPED_INCOMPLETE") {
    throw "Run '$RunId' is not STOPPED_INCOMPLETE (gate=$gateStatus, pointer=$pointerStatus)."
}

$pidCandidates = @($gate.process_ids, $gate.collector_pid, $gate.monitor_pid)
if ($pointer) {
    $pidCandidates += @($pointer.process_ids, $pointer.collector_pid, $pointer.monitor_pid)
}
$liveProcessIds = @(Get-LiveProcessIds -Values $pidCandidates)
if ($liveProcessIds.Count -gt 0) {
    throw "Refusing to reject an active run. Live PID(s): $($liveProcessIds -join ', ')."
}

$now = Get-Date
$rejectedAt = $now.ToString("yyyy-MM-ddTHH:mm:ss.fffffffK")
$stamp = $now.ToString("yyyyMMdd_HHmmssfff")
$safeRunId = $RunId -replace "[^A-Za-z0-9_.-]", "_"
New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
$archivedGatePath = Join-Path $ArchiveDir "active-run-gate.$safeRunId.rejected-incomplete.$stamp.json"
$archivedPointerPath = if ($pointer) {
    Join-Path $ArchiveDir "current-run.$safeRunId.rejected-incomplete.$stamp.json"
} else {
    $null
}

$originalGateStatus = [string]$gate.status
Set-JsonProperty -Object $gate -Name "original_status" -Value $originalGateStatus
Set-JsonProperty -Object $gate -Name "status" -Value "REJECTED_INCOMPLETE"
Set-JsonProperty -Object $gate -Name "gate_status" -Value "REJECTED_INCOMPLETE"
Set-JsonProperty -Object $gate -Name "rejected_at" -Value $rejectedAt
Set-JsonProperty -Object $gate -Name "rejection_reason" -Value $Reason
Set-JsonProperty -Object $gate -Name "replay_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "grid_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "backtest_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "paper_forward_allowed" -Value $false
Write-JsonAtomic -Path $archivedGatePath -Value $gate

if ($pointer) {
    $originalPointerStatus = [string]$pointer.status
    Set-JsonProperty -Object $pointer -Name "original_status" -Value $originalPointerStatus
    Set-JsonProperty -Object $pointer -Name "status" -Value "REJECTED_INCOMPLETE"
    Set-JsonProperty -Object $pointer -Name "rejected_at" -Value $rejectedAt
    Set-JsonProperty -Object $pointer -Name "rejection_reason" -Value $Reason
    Set-JsonProperty -Object $pointer -Name "collector_pid" -Value $null
    Set-JsonProperty -Object $pointer -Name "monitor_pid" -Value $null
    Set-JsonProperty -Object $pointer -Name "process_ids" -Value @()
    Write-JsonAtomic -Path $archivedPointerPath -Value $pointer
}

$resolutionRunId = "resolved_incomplete_$stamp"
$neutralGate = [ordered]@{
    schema = "active_run_gate_v2"
    project = if ($gate.project) { [string]$gate.project } else { "trading_mvp" }
    run_id = $resolutionRunId
    status = "READY_FOR_POSTPROCESS"
    gate_status = "READY_FOR_POSTPROCESS"
    final = $true
    replay_allowed = $false
    grid_allowed = $false
    backtest_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    created_at = $rejectedAt
    updated_at = $rejectedAt
    monitor_pid = $null
    collector_pid = $null
    process_ids = @()
    archived_rejected_gate = $archivedGatePath
    archived_rejected_pointer = $archivedPointerPath
    rejected_run_id = $RunId
    next_goal_decision = $NextGoalDecision
    next_goal_reason = $Reason
    next_step_after_ready = "Proceed with bounded implementation or analysis only. A new collector still requires visible-run approval."
    purpose = "Neutral gate after explicit rejection of an incomplete dataset."
}
$neutralPointer = [ordered]@{
    schema = "active_run_pointer_v1"
    project = $neutralGate.project
    run_id = $resolutionRunId
    status = "READY_FOR_POSTPROCESS"
    updated_at = $rejectedAt
    manifest_path = $null
    output = $null
    collector_pid = $null
    monitor_pid = $null
    process_ids = @()
    launch_record_path = $null
}

Write-JsonAtomic -Path $gatePathResolved -Value $neutralGate
Write-JsonAtomic -Path $PointerPath -Value $neutralPointer

$result = [ordered]@{
    ok = $true
    action = "REJECT_INCOMPLETE"
    rejected_run_id = $RunId
    resolution_run_id = $resolutionRunId
    archived_gate_path = $archivedGatePath
    archived_pointer_path = $archivedPointerPath
    active_gate_path = $gatePathResolved
    current_pointer_path = $PointerPath
    next_goal_decision = $NextGoalDecision
}
if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    $result | Format-List
}
