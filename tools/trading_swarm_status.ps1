param(
    [switch]$Json,
    [string]$WorkflowRoot = "D:\AionUi-Paperclip\docs\agent-workflows"
)

$ErrorActionPreference = "Stop"

function Read-JsonSafe {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Read-TextSafe {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    try {
        return (Get-Content -Raw -LiteralPath $Path)
    } catch {
        return ""
    }
}

function Get-MaxWriteTime {
    param([string[]]$Paths)
    $times = @()
    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path) {
            $times += (Get-Item -LiteralPath $path).LastWriteTime
        }
    }
    if ($times.Count -eq 0) {
        return $null
    }
    return ($times | Sort-Object -Descending | Select-Object -First 1)
}

function Get-HandoffDecision {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }
    $match = [regex]::Match($Text, "(?is)##\s*Решение\s*\r?\n\s*(approve|revise|escalate|block)\b")
    if (-not $match.Success) {
        return $null
    }
    return $match.Groups[1].Value.ToLowerInvariant()
}

function Convert-ToStringArray {
    param($Value)
    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [string]) {
        return @($Value)
    }
    return @($Value | ForEach-Object { [string]$_ })
}

$workflows = @()
$readError = $null

if (Test-Path -LiteralPath $WorkflowRoot) {
    try {
        foreach ($dir in Get-ChildItem -LiteralPath $WorkflowRoot -Directory -ErrorAction Stop) {
            $contractPath = Join-Path $dir.FullName "contract.json"
            $contract = Read-JsonSafe -Path $contractPath
            if ($null -eq $contract) {
                continue
            }

            $briefPath = Join-Path $dir.FullName "brief.md"
            $handoffRel = if ($contract.PSObject.Properties.Name -contains "last_handoff" -and -not [string]::IsNullOrWhiteSpace([string]$contract.last_handoff)) {
                [string]$contract.last_handoff
            } else {
                "handoff.md"
            }
            $handoffPath = Join-Path $dir.FullName $handoffRel
            if (-not (Test-Path -LiteralPath $handoffPath)) {
                $handoffPath = Join-Path $dir.FullName "handoff.md"
            }

            $brief = Read-TextSafe -Path $briefPath
            $handoff = Read-TextSafe -Path $handoffPath
            $title = [string]$contract.title
            $id = [string]$contract.workflow_id
            if ([string]::IsNullOrWhiteSpace($id)) {
                $id = $dir.Name
            }
            $searchText = (@($dir.Name, $id, $title, $brief, $handoff) -join "`n")
            if ($searchText -notmatch "trading[_-]mvp") {
                continue
            }

            $blockers = Convert-ToStringArray -Value $contract.blockers
            $decision = Get-HandoffDecision -Text $handoff
            $combinedStatusText = (@($contract.state, $contract.last_event, $blockers, $handoff) -join "`n")
            $isSwarmLimited = [bool]($combinedStatusText -match "swarm_limited|empty stdout|no DB response|runtime failure")
            $updatedAt = Get-MaxWriteTime -Paths @($contractPath, $briefPath, $handoffPath, (Join-Path $dir.FullName "events.jsonl"))

            $isCancelled = [string]$contract.state -eq "cancelled"
            $workflows += [ordered]@{
                workflow_id = $id
                title = $title
                state = [string]$contract.state
                current_level = [string]$contract.current_level
                last_event = [string]$contract.last_event
                allowed_next_agents = @(Convert-ToStringArray -Value $contract.allowed_next_agents)
                blockers = @($blockers)
                decision = $decision
                handoff_path = $handoffPath
                updated_at = if ($updatedAt) { $updatedAt.ToString("yyyy-MM-dd HH:mm:ss zzz") } else { $null }
                swarm_limited = $isSwarmLimited
                independent_review_available = [bool]((-not $isCancelled) -and (-not $isSwarmLimited) -and -not [string]::IsNullOrWhiteSpace($decision))
            }
        }
    } catch {
        $readError = $_.Exception.Message
    }
} else {
    $readError = "workflow root not found: $WorkflowRoot"
}

$latest = @($workflows | Sort-Object @{ Expression = { if ($_.updated_at) { [datetime]$_.updated_at } else { [datetime]::MinValue } } ; Descending = $true } | Select-Object -First 1)
if ($latest.Count -gt 0) {
    $latest = $latest[0]
} else {
    $latest = $null
}

$status = "NO_TRADING_SWARM_WORKFLOW"
$recommendedAction = "manual_codex_control_until_next_major_checkpoint"
if ($readError) {
    $status = "SWARM_STATUS_UNAVAILABLE"
    $recommendedAction = "continue_manual_codex_and_fix_swarm_status_readback"
} elseif ($latest -and $latest.state -eq "cancelled") {
    $status = "SWARM_CANCELLED_BY_USER"
    $recommendedAction = "continue_manual_codex_control_do_not_restart_swarm_without_user_request"
} elseif ($latest -and [bool]$latest.swarm_limited) {
    $status = "SWARM_LIMITED"
    $recommendedAction = "continue_manual_codex_until_swarm_runtime_recovers"
} elseif ($latest -and $latest.decision -eq "block") {
    $status = "SWARM_BLOCKED"
    $recommendedAction = "respect_swarm_block_until_new_evidence_changes_branch"
} elseif ($latest -and $latest.decision -eq "approve") {
    $status = "SWARM_APPROVED"
    $recommendedAction = "continue_with_gate_rules_and_required_user_approval"
} elseif ($latest -and $latest.state -eq "waiting_for_approval") {
    $status = "SWARM_REVIEW_PENDING_APPROVAL"
    $recommendedAction = "do_not_treat_pending_swarm_review_as_approval"
} elseif ($latest) {
    $status = "SWARM_REVIEW_INCOMPLETE"
    $recommendedAction = "continue_manual_codex_or_retry_swarm_before_major_branch_decision"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_swarm_status"
    workflow_root = $WorkflowRoot
    status = $status
    read_error = $readError
    latest_workflow = $latest
    workflow_count = @($workflows).Count
    swarm_limited = [bool]($latest -and [bool]$latest.swarm_limited)
    independent_review_available = [bool]($latest -and [bool]$latest.independent_review_available)
    recommended_action = $recommendedAction
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "trading_mvp Swarm Status" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Status: $($result.status)"
Write-Host "Workflow root: $WorkflowRoot"
if ($result.read_error) {
    Write-Host "Read error: $($result.read_error)"
}
if ($latest) {
    Write-Host "Latest workflow: $($latest.workflow_id)"
    Write-Host "  title: $($latest.title)"
    Write-Host "  state: $($latest.state)"
    Write-Host "  current level: $($latest.current_level)"
    Write-Host "  decision: $($latest.decision)"
    Write-Host "  swarm_limited: $($latest.swarm_limited)"
    Write-Host "  blockers: $(@($latest.blockers) -join '; ')"
    Write-Host "  handoff: $($latest.handoff_path)"
}
Write-Host "Recommended action: $($result.recommended_action)"
