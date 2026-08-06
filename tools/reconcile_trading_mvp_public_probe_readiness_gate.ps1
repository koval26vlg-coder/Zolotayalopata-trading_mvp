param(
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [string]$CurrentRunPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\current-run.json",
    [string]$BacklogPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\trading-mvp-autopilot-research-backlog.json",
    [string]$AuditPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\paper-product-readiness-audit-v9.json",
    [string]$ReceiptPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\paper-public-readonly-probe-v3-readiness-chain-complete.json",
    [string]$ArchiveDir = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\archived-gates",
    [string]$ExpectedRunId = "paper_public_readonly_probe_v3_20260730_152740",
    [string]$ExpectedTaskId = "paper_product_readiness_audit_v9",
    [switch]$PlanOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    return [System.Convert]::ToHexString($hash).ToLowerInvariant()
}

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
    $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $tempPath -Encoding utf8
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

function Assert-FalseSafetyField {
    param(
        [Parameter(Mandatory = $true)]$Safety,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (
        -not ($Safety.PSObject.Properties.Name -contains $Name) -or
        [bool]$Safety.$Name
    ) {
        throw "Readiness audit safety field must be false: $Name"
    }
}

function Get-DeclaredProcessIds {
    param([Parameter(Mandatory = $true)]$Gate)
    $ids = [System.Collections.Generic.List[int]]::new()
    foreach ($value in @(@($Gate.process_ids) + @($Gate.collector_pid, $Gate.monitor_pid))) {
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
            continue
        }
        $parsed = 0
        if ([int]::TryParse([string]$value, [ref]$parsed) -and $parsed -gt 0) {
            $ids.Add($parsed)
        }
    }
    return @($ids | Sort-Object -Unique)
}

foreach ($requiredPath in @($GatePath, $CurrentRunPath, $BacklogPath, $AuditPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required reconciliation input not found: $requiredPath"
    }
}

$gate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
$pointer = Get-Content -LiteralPath $CurrentRunPath -Raw | ConvertFrom-Json
$backlog = Get-Content -LiteralPath $BacklogPath -Raw | ConvertFrom-Json
$audit = Get-Content -LiteralPath $AuditPath -Raw | ConvertFrom-Json

if ([string]$gate.run_id -ne $ExpectedRunId) {
    throw "Active gate run_id mismatch: expected=$ExpectedRunId actual=$($gate.run_id)"
}
if ([string]$pointer.run_id -ne $ExpectedRunId) {
    throw "Current-run pointer mismatch: expected=$ExpectedRunId actual=$($pointer.run_id)"
}
$gateStatus = [string]$(if ($gate.PSObject.Properties.Name -contains "gate_status") {
    $gate.gate_status
} else {
    $gate.status
})
if ($gateStatus -ne "READY_FOR_POSTPROCESS" -or -not [bool]$gate.final) {
    throw "Gate must be final READY_FOR_POSTPROCESS: status=$gateStatus final=$($gate.final)"
}
if ([string]$pointer.status -ne "READY_FOR_POSTPROCESS") {
    throw "Current-run pointer is not READY_FOR_POSTPROCESS: $($pointer.status)"
}
$declaredProcessIds = @(Get-DeclaredProcessIds -Gate $gate)
if ($declaredProcessIds.Count -gt 0) {
    throw "Gate still declares process ids; refuse postprocess reconciliation."
}

$probeEvidencePath = [string]$gate.evidence_path
if (-not $probeEvidencePath -or -not (Test-Path -LiteralPath $probeEvidencePath -PathType Leaf)) {
    throw "Gate probe evidence is missing: $probeEvidencePath"
}
$probeEvidenceSha = Get-FileSha256 -Path $probeEvidencePath
if ($probeEvidenceSha -ne [string]$gate.evidence_file_sha256) {
    throw "Gate probe evidence SHA256 mismatch."
}

$task = @($backlog.tasks | Where-Object { [string]$_.id -eq $ExpectedTaskId })
if ($task.Count -ne 1) {
    throw "Expected exactly one backlog task '$ExpectedTaskId', found $($task.Count)."
}
$task = $task[0]
if ([string]$task.status -ne "COMPLETED") {
    throw "Backlog task is not COMPLETED: $($task.status)"
}
$normalizedAudit = Get-NormalizedPath -Path $AuditPath
$normalizedTaskArtifact = Get-NormalizedPath -Path ([string]$task.artifact_path)
if (-not $normalizedAudit.Equals(
    $normalizedTaskArtifact,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Backlog artifact path does not match requested audit path."
}
$auditSha = Get-FileSha256 -Path $AuditPath
if ($auditSha -ne [string]$task.artifact_sha256) {
    throw "Readiness audit SHA256 does not match completed backlog evidence."
}
if ([string]$audit.schema -ne "trading_mvp_paper_product_readiness_audit_v9") {
    throw "Unexpected readiness audit schema: $($audit.schema)"
}
if ([string]$audit.public_data_plane.readonly_probe_run_id -ne $ExpectedRunId) {
    throw "Readiness audit is not bound to the active probe run."
}
if ([string]$audit.public_data_plane.readonly_probe_evidence -ne "V3_ACCEPTED") {
    throw "Readiness audit does not accept the v3 probe evidence."
}
if (
    [string]$audit.verdict -ne
    "PUBLIC_PROBE_EVIDENCE_BINDING_COMPLETE_NO_MATERIAL_OFFLINE_GAPS_EDGE_AND_FORWARD_GATES_REMAIN_BLOCKED"
) {
    throw "Unexpected readiness audit verdict: $($audit.verdict)"
}
if ([string]$audit.next_allowed_action -ne "WAITING_SCHEDULE_WINDOW_NO_FALLBACK") {
    throw "Unexpected readiness audit next_allowed_action: $($audit.next_allowed_action)"
}
foreach ($field in @(
    "returns_or_pnl_read",
    "oos_read",
    "signals_read",
    "hypothesis_changed",
    "network_collection",
    "grid_or_retune",
    "paper_forward_started",
    "live_orders",
    "private_api_keys",
    "leverage",
    "margin"
)) {
    Assert-FalseSafetyField -Safety $audit.safety -Name $field
}
if ([bool]$audit.evidence_gates.edge_proven) {
    throw "Readiness audit unexpectedly marks edge_proven=true."
}
if ([bool]$audit.evidence_gates.replay_allowed) {
    throw "Readiness audit unexpectedly marks replay_allowed=true."
}

$effectiveDecision = "PUBLIC_READONLY_PROBE_READINESS_CHAIN_COMPLETE"
$priorDecision = [string]$gate.next_goal_decision
if (
    $priorDecision -eq $effectiveDecision -and
    (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)
) {
    $priorReceipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
    $priorDecision = [string]$priorReceipt.prior_next_goal_decision
}
$receiptCore = [ordered]@{
    schema = "trading_mvp_gate_postprocess_reconciliation_v1"
    project = "trading_mvp"
    run_id = $ExpectedRunId
    prior_next_goal_decision = $priorDecision
    effective_next_goal_decision = $effectiveDecision
    probe_evidence_path = $probeEvidencePath
    probe_evidence_sha256 = $probeEvidenceSha
    readiness_task_id = $ExpectedTaskId
    readiness_audit_path = $normalizedAudit
    readiness_audit_sha256 = $auditSha
    readiness_audit_schema = [string]$audit.schema
    readiness_audit_verdict = [string]$audit.verdict
    readiness_deterministic_result_hash = [string]$audit.deterministic_result_hash
    maximum_authority = [string]$audit.maximum_authority
    replay_allowed = $false
    edge_proven = $false
    paper_forward_ready = $false
    live_review_eligible = $false
}
$deterministicHash = Get-TextSha256 -Text (
    $receiptCore | ConvertTo-Json -Depth 20 -Compress
)
$now = [DateTimeOffset]::Now.ToString("o")
$receipt = [ordered]@{}
foreach ($entry in $receiptCore.GetEnumerator()) {
    $receipt[$entry.Key] = $entry.Value
}
$receipt["deterministic_result_hash"] = $deterministicHash
$receipt["generated_at_utc"] = [DateTimeOffset]::UtcNow.ToString("o")

$existingReceiptReused = $false
if (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) {
    $existingReceipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
    if ([string]$existingReceipt.deterministic_result_hash -ne $deterministicHash) {
        throw "Immutable reconciliation receipt already exists with different evidence."
    }
    $receipt = $existingReceipt
    $existingReceiptReused = $true
}

$alreadyReconciled = (
    [string]$gate.next_goal_decision -eq $effectiveDecision -and
    $gate.PSObject.Properties.Name -contains "downstream_readiness_reconciliation" -and
    [string]$gate.downstream_readiness_reconciliation.deterministic_result_hash -eq $deterministicHash
)

$result = [ordered]@{
    decision = if ($PlanOnly) {
        "PUBLIC_PROBE_READINESS_GATE_RECONCILIATION_PLAN_VALID"
    } elseif ($alreadyReconciled) {
        "PUBLIC_PROBE_READINESS_GATE_RECONCILIATION_REUSED"
    } else {
        "PUBLIC_PROBE_READINESS_GATE_RECONCILED"
    }
    run_id = $ExpectedRunId
    prior_next_goal_decision = $priorDecision
    effective_next_goal_decision = $effectiveDecision
    readiness_audit_path = $normalizedAudit
    readiness_audit_sha256 = $auditSha
    deterministic_result_hash = $deterministicHash
    receipt_path = Get-NormalizedPath -Path $ReceiptPath
    receipt_reused = $existingReceiptReused
    gate_updated = $false
    pointer_updated = $false
    archived_gate_path = $null
    archived_pointer_path = $null
    safety = [ordered]@{
        returns_or_pnl_read = $false
        oos_read = $false
        hypothesis_changed = $false
        network_collection = $false
        grid_or_retune = $false
        replay_allowed = $false
        paper_forward_started = $false
        live_orders = $false
        private_api_keys = $false
        leverage_or_margin = $false
    }
}

if (-not $PlanOnly -and -not $alreadyReconciled) {
    if (-not $existingReceiptReused) {
        Write-JsonAtomic -Path $ReceiptPath -Value $receipt
    }
    $receiptSha = Get-FileSha256 -Path $ReceiptPath

    New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
    $stamp = [DateTimeOffset]::Now.ToString("yyyyMMdd_HHmmssfff")
    $safeRunId = $ExpectedRunId -replace "[^A-Za-z0-9_.-]", "_"
    $archivedGatePath = Join-Path $ArchiveDir (
        "active-run-gate.$safeRunId.pre-readiness-reconcile.$stamp.json"
    )
    $archivedPointerPath = Join-Path $ArchiveDir (
        "current-run.$safeRunId.pre-readiness-reconcile.$stamp.json"
    )
    Copy-Item -LiteralPath $GatePath -Destination $archivedGatePath
    Copy-Item -LiteralPath $CurrentRunPath -Destination $archivedPointerPath

    $binding = [ordered]@{
        status = "COMPLETE"
        receipt_path = Get-NormalizedPath -Path $ReceiptPath
        receipt_sha256 = $receiptSha
        deterministic_result_hash = $deterministicHash
        readiness_task_id = $ExpectedTaskId
        readiness_audit_path = $normalizedAudit
        readiness_audit_sha256 = $auditSha
        readiness_audit_verdict = [string]$audit.verdict
        reconciled_at = $now
    }
    Set-JsonProperty -Object $gate -Name "updated_at" -Value $now
    Set-JsonProperty -Object $gate -Name "downstream_readiness_reconciliation" -Value $binding
    Set-JsonProperty -Object $gate -Name "readiness_output_path" -Value $normalizedAudit
    Set-JsonProperty -Object $gate -Name "next_goal_decision" -Value $effectiveDecision
    Set-JsonProperty -Object $gate -Name "next_goal_reason" -Value (
        "Probe evidence postprocess and readiness audit v9 are hash-bound and complete; edge, replay, paper-forward, and live gates remain closed."
    )
    Set-JsonProperty -Object $gate -Name "next_step_after_ready" -Value (
        "Follow the trading_mvp autopilot guard and immutable PIT schedule. Do not replay this public-readonly probe or treat it as edge evidence."
    )
    Set-JsonProperty -Object $gate -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gate -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gate -Name "backtest_allowed" -Value $false
    Set-JsonProperty -Object $gate -Name "paper_forward_allowed" -Value $false

    Set-JsonProperty -Object $pointer -Name "updated_at" -Value $now
    Set-JsonProperty -Object $pointer -Name "downstream_readiness_reconciliation" -Value $binding

    Write-JsonAtomic -Path $GatePath -Value $gate
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer

    $result.gate_updated = $true
    $result.pointer_updated = $true
    $result.archived_gate_path = $archivedGatePath
    $result.archived_pointer_path = $archivedPointerPath
} elseif (-not $PlanOnly) {
    $result.gate_updated = $false
    $result.pointer_updated = $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 20
} else {
    [pscustomobject]$result | Format-List
}
