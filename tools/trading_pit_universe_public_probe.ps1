param(
    [string]$OutputPath = "",
    [int]$MinContractsPerExchange = 50,
    [int]$TimeoutSec = 10,
    [switch]$ConfirmedPublicProbe,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\pit_universe_public_probe.py"

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
        $compact = [ordered]@{}
        foreach ($property in $Payload.PSObject.Properties) {
            if ($property.Name -ne "rows") {
                $compact[$property.Name] = $property.Value
            }
        }
        if ($Payload.PSObject.Properties.Name -contains "rows") {
            $compact["rows_omitted_from_stdout"] = @($Payload.rows).Count
        }
        $compact | ConvertTo-Json -Depth 18
        return
    }

    Write-Host "PIT Universe Public Probe" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Confirmed public probe: $($Payload.confirmed_public_probe)"
    Write-Host "Output: $OutputPath"
    Write-Host "Gate updated: $($Payload.gate_updated)"
    if ($Payload.summary) {
        Write-Host "Rows total: $($Payload.summary.rows_total)"
    }
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resume/reject incomplete run before public probe."
}

$gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$allowedByDecision = [string]$gateDoc.next_goal_decision -eq "PIT_UNIVERSE_SNAPSHOT_PREFLIGHT_PLANONLY_READY_FOR_PUBLIC_PROBE"
$allowedByBranch = (
    $gateDoc.strategy_branch_status -and
    [string]$gateDoc.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
    [string]$gateDoc.strategy_branch_status.verdict -in @(
        "pit_snapshot_preflight_ready_for_public_probe",
        "pit_public_probe_plan_ready",
        "pit_public_probe_accepted_ready_for_visible_snapshot_collect_approval",
        "pit_public_probe_rejected"
    )
)
if (-not ($allowedByDecision -or $allowedByBranch)) {
    throw "PIT universe public probe is not the active gate step. Current next_goal_decision=$($gateDoc.next_goal_decision)"
}

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $name = if ($ConfirmedPublicProbe) { "pit_universe_public_probe_$timestamp.json" } else { "pit_universe_public_probe_plan_$timestamp.json" }
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\$name"
}

$python = Resolve-Python
$argsList = @(
    $modulePath,
    "--out", $OutputPath,
    "--min-contracts-per-exchange", ([string]$MinContractsPerExchange),
    "--timeout-sec", ([string]$TimeoutSec)
)
if ($ConfirmedPublicProbe) {
    $argsList += "--probe"
}

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "pit_universe_public_probe.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

$confirmedCommand = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
    "-MinContractsPerExchange $MinContractsPerExchange",
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
    confirmed_public_probe = $confirmedCommand
    active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
})

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $gateDecision = switch ($decision) {
        "PIT_UNIVERSE_PUBLIC_PROBE_PLAN_READY" { "PIT_UNIVERSE_SNAPSHOT_PREFLIGHT_PLANONLY_READY_FOR_PUBLIC_PROBE" }
        "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL" { "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL" }
        default { "PIT_UNIVERSE_PUBLIC_PROBE_REJECTED_RESCOPE" }
    }
    $verdict = switch ($decision) {
        "PIT_UNIVERSE_PUBLIC_PROBE_PLAN_READY" { "pit_public_probe_plan_ready" }
        "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL" { "pit_public_probe_accepted_ready_for_visible_snapshot_collect_approval" }
        default { "pit_public_probe_rejected" }
    }
    $nextStep = switch ($gateDecision) {
        "PIT_UNIVERSE_SNAPSHOT_PREFLIGHT_PLANONLY_READY_FOR_PUBLIC_PROBE" {
            "Run short foreground PIT universe public probe; no long collect/grid/live/API/paper-forward."
        }
        "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL" {
            "Build visible PIT universe snapshot collector approval packet. Actual collect still requires explicit user confirmation."
        }
        default {
            "Reject or rescope forward_pit_universe_event_liquidity_anomaly before collect/replay/grid/live/API/paper-forward."
        }
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $gateDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "PIT universe public probe updated. Research-only; replay/grid/live/API/paper-forward remain blocked."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_public_probe" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_approval" -Value $confirmedCommand
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "forward_pit_universe_event_liquidity_anomaly"
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
        next_step_required = if ($gateDecision -eq "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL") { "build_visible_pit_snapshot_collect_approval_packet" } elseif ($gateDecision -eq "PIT_UNIVERSE_PUBLIC_PROBE_REJECTED_RESCOPE") { "rescope_or_reject_branch" } else { "run_short_pit_universe_public_probe" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_public_probe_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_public_probe_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_public_probe_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_public_probe_confirmed" -Value ([bool]$ConfirmedPublicProbe)
    $gateDoc | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    Set-JsonProperty -Object $result -Name "gate_updated" -Value $true
}

$result | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Result -Payload $result
