param(
    [string]$OutputPath = "",
    [string]$PreflightPath = "",
    [int]$MaxBases = 10,
    [int]$MinSuccessBases = 5,
    [int]$DepthLimit = 5,
    [int]$TimeoutSec = 10,
    [switch]$ConfirmedPublicProbe,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\spot_perp_basis_public_probe.py"

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
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Write-Result {
    param($Payload)

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }

    Write-Host "Spot/Perp Basis Public Probe" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Confirmed public probe: $($Payload.confirmed_public_probe)"
    Write-Host "Output: $OutputPath"
    Write-Host "Gate updated: $($Payload.gate_updated)"
    Write-Host ""
    Write-Host "Next valid moves" -ForegroundColor Yellow
    foreach ($move in @($Payload.next_valid_moves)) {
        Write-Host "  - $move"
    }
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ($gate.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ($gate.status -eq "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resume/reject the incomplete run before public probe planning."
}

$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$allowedByDecision = [string]$gateDoc.next_goal_decision -eq "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE"
$allowedByBranch = (
    $gateDoc.strategy_branch_status -and
    [string]$gateDoc.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
    [string]$gateDoc.strategy_branch_status.verdict -in @("availability_preflight_ready_for_public_probe", "public_probe_plan_ready_awaiting_confirmation")
)
if (-not ($allowedByDecision -or $allowedByBranch)) {
    throw "spot/perp public probe is not the active gate step. Current next_goal_decision=$($gateDoc.next_goal_decision)"
}

if (-not $PreflightPath) {
    $PreflightPath = [string]$gateDoc.last_spot_perp_basis_availability_preflight_output_path
}
if (-not $PreflightPath) {
    $latest = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "spot_perp_basis_availability_preflight_*.json" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) { $PreflightPath = $latest.FullName }
}
if (-not $PreflightPath -or -not (Test-Path -LiteralPath $PreflightPath)) {
    throw "Availability preflight artifact not found. Pass -PreflightPath."
}

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $name = if ($ConfirmedPublicProbe) { "spot_perp_basis_public_probe_$timestamp.json" } else { "spot_perp_basis_public_probe_plan_$timestamp.json" }
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\$name"
}

$python = Resolve-Python
$argsList = @(
    $modulePath,
    "--preflight", $PreflightPath,
    "--out", $OutputPath,
    "--max-bases", ([string]$MaxBases),
    "--min-success-bases", ([string]$MinSuccessBases),
    "--depth-limit", ([string]$DepthLimit),
    "--timeout-sec", ([string]$TimeoutSec)
)
if ($ConfirmedPublicProbe) {
    $argsList += "--probe"
}

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "spot_perp_basis_public_probe.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

$confirmedCommand = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
    "-PreflightPath `"$PreflightPath`"",
    "-MaxBases $MaxBases",
    "-MinSuccessBases $MinSuccessBases",
    "-DepthLimit $DepthLimit",
    "-TimeoutSec $TimeoutSec",
    "-ConfirmedPublicProbe",
    "-UpdateGate",
    "-Json"
) -join " "

Set-JsonProperty -Object $result -Name "gate_status" -Value $gate.status
Set-JsonProperty -Object $result -Name "gate_next_goal_decision_before" -Value $gateDoc.next_goal_decision
Set-JsonProperty -Object $result -Name "gate_updated" -Value $false
Set-JsonProperty -Object $result -Name "commands" -Value ([ordered]@{
    plan_only = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
    confirmed_public_probe_after_user_confirmation = $confirmedCommand
    active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
})

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $gateDecision = switch ($decision) {
        "SPOT_PERP_BASIS_PUBLIC_PROBE_PLAN_READY_AWAITING_CONFIRMATION" { "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE" }
        "SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" { "SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" }
        default { "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE" }
    }
    $verdict = switch ($decision) {
        "SPOT_PERP_BASIS_PUBLIC_PROBE_PLAN_READY_AWAITING_CONFIRMATION" { "public_probe_plan_ready_awaiting_confirmation" }
        "SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" { "public_probe_accepted_ready_for_collect_approval_packet" }
        default { "public_probe_rejected" }
    }
    $nextStep = switch ($gateDecision) {
        "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE" {
            "Await explicit confirmation, then run command_after_explicit_approval for the short visible public REST spot/perp probe. Do not start collect/grid/replay/live/API/paper-forward."
        }
        "SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" {
            "Build visible spot/perp snapshot collect approval packet. Actual collect still requires explicit user confirmation; no replay/grid/live/API/paper-forward."
        }
        default {
            "Reject or rescope spot_perp_basis_mean_reversion_no_funding before collect/grid/replay/live/API/paper-forward."
        }
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $gateDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "spot/perp public probe planning/result updated. This remains research-only and blocks replay/grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_public_probe" -Value (-not $ConfirmedPublicProbe)
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_approval" -Value $confirmedCommand
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "spot_perp_basis_mean_reversion_no_funding"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = if ($ConfirmedPublicProbe) { "build_collect_approval_packet_or_rescope" } else { "await_confirmation_for_short_public_probe" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_public_probe_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_public_probe_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_public_probe_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_public_probe_confirmed" -Value ([bool]$ConfirmedPublicProbe)
    $gateDoc | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    Set-JsonProperty -Object $result -Name "gate_updated" -Value $true
}

$result | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Result -Payload $result
