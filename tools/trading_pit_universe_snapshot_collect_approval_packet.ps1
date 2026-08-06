param(
    [string]$OutputPath = "",
    [double]$Hours = 24,
    [int]$IntervalSec = 300,
    [int]$TimeoutSec = 10,
    [int]$MinContractsPerExchange = 50,
    [string]$OutputRoot = "E:\trading_mvp\pit-universe-snapshots",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$visibleCollectScript = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\pit_universe_snapshot_collect_approval_packet_$timestamp.json"
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

function Save-Result {
    param($Payload)
    $outDir = Split-Path -Parent $OutputPath
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }
    Write-Host "PIT Universe Snapshot Collect Approval Packet" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $OutputPath"
    Write-Host "Command after explicit approval:"
    Write-Host "  $($Payload.command_after_explicit_approval)"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "pit_universe_snapshot_collect_approval_packet"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        reason = "Active run gate is $($gate.status); only status/resume handling is allowed."
        would_start = $false
        research_only = $true
        output_path = $OutputPath
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$allowed = (
    [string]$gateDoc.next_goal_decision -eq "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL" -or
    (
        $gateDoc.strategy_branch_status -and
        [string]$gateDoc.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gateDoc.strategy_branch_status.verdict -eq "pit_public_probe_accepted_ready_for_visible_snapshot_collect_approval"
    )
)
if (-not $allowed) {
    throw "PIT universe snapshot collect approval packet is not the active gate step. Current next_goal_decision=$($gateDoc.next_goal_decision)"
}

$runId = "pit_universe_snapshot_collect_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$durationSec = [int][Math]::Round($Hours * 3600)
$runDir = Join-Path $OutputRoot $runId
$snapshotPath = Join-Path $runDir "snapshots.jsonl"
$manifestPath = Join-Path $runDir "manifest.json"
$commandAfterApproval = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$visibleCollectScript`"",
    "-Hours $Hours",
    "-IntervalSec $IntervalSec",
    "-TimeoutSec $TimeoutSec",
    "-MinContractsPerExchange $MinContractsPerExchange",
    "-OutputRoot `"$OutputRoot`"",
    "-RunId $RunId",
    "-ConfirmedPitUniverseSnapshotCollect"
) -join " "

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "pit_universe_snapshot_collect_approval_packet"
    decision = "PIT_UNIVERSE_SNAPSHOT_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"
    selected_branch = "forward_pit_universe_event_liquidity_anomaly"
    would_start = $false
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    actual_collect_requires_explicit_confirmation = $true
    params = [ordered]@{
        hours = $Hours
        duration_sec = $durationSec
        interval_sec = $IntervalSec
        timeout_sec = $TimeoutSec
        min_contracts_per_exchange = $MinContractsPerExchange
        output_root = $OutputRoot
        run_id = $runId
    }
    expected_outputs = [ordered]@{
        run_dir = $runDir
        snapshots_path = $snapshotPath
        manifest_path = $manifestPath
    }
    command_after_explicit_approval = $commandAfterApproval
    next_valid_moves = @(
        "If user explicitly confirms actual collect, run command_after_explicit_approval in a visible terminal.",
        "While collect is RUNNING, only status/ETA checks are allowed.",
        "After collect finishes, run PIT universe data-quality before any replay/grid/live/API/paper-forward."
    )
    blocked_moves = @(
        "hidden_background_collect",
        "collect_without_explicit_confirmation",
        "replay",
        "grid_search",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward"
    )
    gate_updated = $false
    output_path = $OutputPath
}

if ($UpdateGate) {
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $result.decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "PIT universe snapshot collect approval packet is ready. Actual visible collect requires explicit confirmation."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Await explicit confirmation for visible PIT universe snapshot collect; no collect/replay/grid/live/API/paper-forward before confirmation."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $gateDoc.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_approval" -Value $commandAfterApproval
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "forward_pit_universe_event_liquidity_anomaly"
        verdict = "snapshot_collect_approval_packet_ready_awaiting_explicit_confirmation"
        decision_source = $OutputPath
        selected_at = $result.generated_at
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = "await_explicit_confirmation_for_visible_snapshot_collect"
    })
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_snapshot_collect_approval_packet_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_snapshot_collect_approval_packet_decision" -Value $result.decision
    $gateDoc | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
}

Save-Result -Payload $result
