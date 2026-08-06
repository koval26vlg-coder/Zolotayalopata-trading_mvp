param(
    [string]$ProbePath = "",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$modulePath = Join-Path $repoRoot "trading_mvp\src\pit_cross_venue_forward_plan.py"
$visibleWrapper = Join-Path $repoRoot "tools\start_pit_cross_venue_forward_oos_visible.ps1"
$analysisRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param($Object, [string]$Path)
    $temp = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

$gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ([string]$gateStatus.status -eq "STOPPED_INCOMPLETE") {
    throw "Active run is STOPPED_INCOMPLETE. Resume or explicitly reject it before creating a new packet."
}

$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($ProbePath)) {
    $ProbePath = [string]$gate.last_pit_linear_perp_forward_probe_output_path
}
if ([string]::IsNullOrWhiteSpace($ProbePath)) {
    $latest = Get-ChildItem -LiteralPath $analysisRoot -Filter "pit_linear_perp_forward_public_probe_*.json" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) { $ProbePath = $latest.FullName }
}
if ([string]::IsNullOrWhiteSpace($ProbePath) -or -not (Test-Path -LiteralPath $ProbePath -PathType Leaf)) {
    throw "Accepted forward public probe not found. Pass -ProbePath explicitly."
}
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $analysisRoot ("pit_linear_perp_forward_oos_planonly_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
}
if (-not (Test-Path -LiteralPath $analysisRoot)) {
    New-Item -ItemType Directory -Path $analysisRoot -Force | Out-Null
}

$python = Resolve-Python
& $python $modulePath --probe $ProbePath --out $OutputPath | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Forward OOS approval packet builder failed with exit code $LASTEXITCODE"
}
$plan = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
$planHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
$probeCostPositivePairs = [int]$plan.probe_diagnostics.one_shot_cost_positive_pairs
$goalReason = if ($probeCostPositivePairs -gt 0) {
    "ONE_SHOT_PUBLIC_PROBE_PASSED_IDENTITY_DEPTH_TIMESTAMP_FUNDING_AND_FOUND_STRESS_COST_POSITIVE_OBSERVATION"
} else {
    "ONE_SHOT_PUBLIC_PROBE_PASSED_IDENTITY_DEPTH_TIMESTAMP_FUNDING_BUT_FOUND_ZERO_STRESS_COST_POSITIVE_PAIRS"
}
$startCommand = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$visibleWrapper`"",
    "-PlanPath `"$OutputPath`"",
    "-ConfirmedForwardOosCollect"
) -join " "

if ($UpdateGate) {
    Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gate "status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gate "gate_status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gate "next_goal_decision" "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"
    Set-JsonProperty $gate "next_goal_reason" $goalReason
    Set-JsonProperty $gate "next_step_after_ready" "Await explicit user approval for a visible forward-OOS collect. Do not start collect/replay/grid/live/API-key/paper-forward automatically."
    Set-JsonProperty $gate "last_pit_linear_perp_forward_probe_output_path" $ProbePath
    Set-JsonProperty $gate "last_pit_linear_perp_forward_probe_decision" "PIT_LINEAR_PERP_FORWARD_PROBE_ACCEPTED_READY_FOR_OOS_APPROVAL_PACKET"
    Set-JsonProperty $gate "forward_oos_plan_path" $OutputPath
    Set-JsonProperty $gate "forward_oos_plan_sha256" $planHash
    Set-JsonProperty $gate "readiness_output_path" $OutputPath
    Set-JsonProperty $gate "requires_explicit_user_approval_for_actual_collect" $true
    Set-JsonProperty $gate "command_after_explicit_approval" $startCommand
    Set-JsonProperty $gate "replay_allowed" $false
    Set-JsonProperty $gate "grid_allowed" $false
    Set-JsonProperty $gate "paper_forward_allowed" $false
    Set-JsonProperty $gate "live_orders" $false
    Set-JsonProperty $gate "api_keys" $false
    Set-JsonProperty $gate "leverage_or_margin" $false
    Set-JsonProperty $gate "strategy_branch_status" ([ordered]@{
        branch = "pit_linear_perp_cross_venue_forward_oos"
        verdict = "approval_packet_ready_awaiting_explicit_visible_collect_confirmation"
        all_discovery_bases = @($plan.sealed_universe.all_discovery_bases).Count
        identity_evaluation_bases = @($plan.sealed_universe.identity_evaluation_bases).Count
        identity_quarantine_bases = @($plan.sealed_universe.identity_quarantine_bases).Count
        one_shot_cost_positive_pairs = [int]$plan.probe_diagnostics.one_shot_cost_positive_pairs
        target_valid_cycles = [int]$plan.collection_contract.target_valid_cycles
        min_valid_pairs_per_cycle = [int]$plan.collection_contract.min_valid_pairs_per_cycle
        min_active_span_sec = [int]$plan.collection_contract.min_active_span_sec
        max_active_duration_sec = [int]$plan.collection_contract.max_active_duration_sec
        strategy_accepted = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
    })
    Write-JsonAtomic -Object $gate -Path $gatePath
}

$result = [ordered]@{
    mode = "pit_linear_perp_forward_oos_approval_packet"
    decision = [string]$plan.decision
    output_path = $OutputPath
    output_sha256 = $planHash
    probe_path = $ProbePath
    all_discovery_bases = @($plan.sealed_universe.all_discovery_bases).Count
    identity_evaluation_bases = @($plan.sealed_universe.identity_evaluation_bases).Count
    identity_quarantine_bases = @($plan.sealed_universe.identity_quarantine_bases).Count
    target_valid_cycles = [int]$plan.collection_contract.target_valid_cycles
    min_valid_pairs_per_cycle = [int]$plan.collection_contract.min_valid_pairs_per_cycle
    min_active_span_hours = [double]$plan.collection_contract.min_active_span_sec / 3600.0
    max_active_duration_hours = [double]$plan.collection_contract.max_active_duration_sec / 3600.0
    would_start = $false
    gate_updated = [bool]$UpdateGate
    requires_explicit_user_approval_for_actual_collect = $true
    command_after_explicit_approval = $startCommand
}
if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "Forward-OOS approval packet" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Plan: $OutputPath"
    Write-Host "Universe: $($result.all_discovery_bases) all / $($result.identity_evaluation_bases) identity / $($result.identity_quarantine_bases) quarantine"
    Write-Host "Quota: $($result.target_valid_cycles) valid cycles; >=$($result.min_valid_pairs_per_cycle) valid pairs/cycle; $($result.min_active_span_hours)-$($result.max_active_duration_hours)h"
    Write-Host "No collect started. Explicit approval is still required."
}
