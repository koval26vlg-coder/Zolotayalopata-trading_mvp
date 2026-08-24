param(
    [string]$OutputPath = "exports\trading-mvp\analysis\spot_perp_basis_collect_approval_packet_current.json",
    [double]$Hours = 72,
    [int]$IntervalSec = 300,
    [int]$TimeoutSec = 10,
    [string]$OutputRoot = "E:\trading_mvp\spot-perp-basis-snapshots",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$nextGoalStepScript = Join-Path $repoRoot "tools\trading_next_goal_step.ps1"
$goalStatusScript = Join-Path $repoRoot "tools\trading_goal_status.ps1"
$preflightScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_availability_preflight.ps1"
$probeScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_public_probe.ps1"
$planonlyScript = Join-Path $repoRoot "tools\trading_spot_perp_basis_mean_reversion_planonly.ps1"

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
    $resolvedOut = Resolve-RepoPath -Path $OutputPath
    $outDir = Split-Path -Parent $resolvedOut
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $resolvedOut -Encoding UTF8
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }
    Write-Host "Spot/Perp Basis Collect Approval Packet" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $resolvedOut"
    Write-Host "Command after explicit approval:"
    Write-Host "  $($Payload.command_after_explicit_approval)"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "spot_perp_basis_collect_approval_packet"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        reason = "Active run gate is $($gate.status); only status/resume handling is allowed."
        would_start = $false
        research_only = $true
        output_path = (Resolve-RepoPath -Path $OutputPath)
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$allowed = (
    [string]$gateDoc.next_goal_decision -in @("SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET", "SPOT_PERP_BASIS_COLLECT_AWAITING_EXPLICIT_USER_APPROVAL") -or
    (
        $gateDoc.strategy_branch_status -and
        [string]$gateDoc.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
        [string]$gateDoc.strategy_branch_status.verdict -in @("public_probe_accepted_ready_for_collect_approval_packet", "collect_approval_packet_ready_awaiting_user_approval")
    )
)
if (-not $allowed) {
    throw "Spot/perp basis collect approval packet is not the active gate step. Current next_goal_decision=$($gateDoc.next_goal_decision)"
}

$latestProbePath = if ($gateDoc.last_spot_perp_basis_public_probe_output_path) {
    [string]$gateDoc.last_spot_perp_basis_public_probe_output_path
} else {
    $probeFiles = Get-ChildItem -LiteralPath (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "spot_perp_basis_public_probe_*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($probeFiles) { $probeFiles.FullName } else { "" }
}

if (-not (Test-Path -LiteralPath $latestProbePath)) {
    throw "Required probe output file not found: $latestProbePath"
}

$probeResult = Get-Content -Raw -LiteralPath $latestProbePath | ConvertFrom-Json
$validatedBases = @()
if ($probeResult.rows) {
    foreach ($r in $probeResult.rows) {
        $mexcOk = $r.venues.mexc -and $r.venues.mexc.ok
        $gateOk = $r.venues.gateio -and $r.venues.gateio.ok
        if ($mexcOk -and $gateOk) {
            $validatedBases += [string]$r.base
        }
    }
}

$runId = "spot_perp_basis_collect_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$durationSec = [int][Math]::Round($Hours * 3600)
$runDir = Join-Path $OutputRoot $runId
$snapshotPath = Join-Path $runDir "snapshots.jsonl"
$manifestPath = Join-Path $runDir "manifest.json"

$commandAfterApproval = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\tools\start_spot_perp_basis_snapshot_collect_visible.ps1`"",
    "-Hours $Hours",
    "-IntervalSec $IntervalSec",
    "-TimeoutSec $TimeoutSec",
    "-Bases `"$($validatedBases -join ',')`"",
    "-OutputRoot `"$OutputRoot`"",
    "-RunId $runId",
    "-ConfirmedSpotPerpBasisCollect"
) -join " "

$packet = [ordered]@{
    schema = "spot_perp_basis_collect_approval_packet_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    decision = "SPOT_PERP_BASIS_COLLECT_APPROVAL_PACKET_READY"
    selected_branch = "spot_perp_basis_mean_reversion_no_funding"
    research_only = $true
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    strategy_accepted = $false
    requires_user_approval = $true
    requires_user_approval_for_actual_collect = $true
    required_user_phrase = "подтверждаю visible spot-perp basis snapshot collect"
    probe_reference = [ordered]@{
        path = $latestProbePath
        sha256 = (Get-FileHash -LiteralPath $latestProbePath -Algorithm SHA256).Hash.ToLowerInvariant()
        decision = $probeResult.decision
        paired_ok_bases = $validatedBases
        paired_ok_count = $validatedBases.Count
    }
    execution_plan = [ordered]@{
        run_id = $runId
        hours = $Hours
        interval_sec = $IntervalSec
        timeout_sec = $TimeoutSec
        output_root = $OutputRoot
        output_dir = $runDir
        snapshot_path = $snapshotPath
        manifest_path = $manifestPath
        bases = $validatedBases
        venues = @("mexc", "gateio")
    }
    economics_guard = [ordered]@{
        min_entry_basis_hurdle_bps = 80.0
        roundtrip_fee_bps = 40.0
        slippage_buffer_bps = 20.0
        adverse_funding_buffer_bps = 20.0
        funding_counted_as_pnl = $false
    }
    command_after_explicit_approval = $commandAfterApproval
    output_path = (Resolve-RepoPath -Path $OutputPath)
    gate_updated = [bool]$UpdateGate
}

if ($UpdateGate) {
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value "SPOT_PERP_BASIS_COLLECT_AWAITING_EXPLICIT_USER_APPROVAL"
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Spot/perp basis collection packet constructed. Awaiting explicit user confirmation before launching visible collector."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Await explicit confirmation: '$($packet.required_user_phrase)' before starting visible snapshot collector."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value "Await explicit confirmation: '$($packet.required_user_phrase)' before starting visible snapshot collector."
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_approval" -Value $commandAfterApproval
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_collect_approval_packet_path" -Value (Resolve-RepoPath -Path $OutputPath)
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "spot_perp_basis_mean_reversion_no_funding"
        verdict = "collect_approval_packet_ready_awaiting_user_approval"
        decision_source = (Resolve-RepoPath -Path $OutputPath)
        selected_at = $packet.generated_at
    })
    $gateDoc | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $packet.gate_updated = $true
}

Save-Result -Payload $packet
