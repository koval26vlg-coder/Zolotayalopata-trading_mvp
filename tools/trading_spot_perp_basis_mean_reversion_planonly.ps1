param(
    [string]$OutputPath = "",
    [string]$DailyRunDir = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\spot_perp_basis_mean_reversion.py"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\spot_perp_basis_mean_reversion_planonly_$timestamp.json"
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
    $Payload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 16
        return
    }

    Write-Host "Spot/Perp Basis Mean-Reversion PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Selected branch: $($Payload.selected_branch)"
    Write-Host "Output: $OutputPath"
    Write-Host "Gate updated: $($Payload.gate_updated)"
    Write-Host ""
    Write-Host "Next valid moves" -ForegroundColor Yellow
    foreach ($move in @($Payload.next_valid_moves)) {
        Write-Host "  - $move"
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
    if ($pythonCmd) {
        return $pythonCmd.Source
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return $pythonCmd.Source
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

$gateRaw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
if ($LASTEXITCODE -ne 0) {
    throw "check_active_run_gate failed with exit code $LASTEXITCODE"
}
$gate = $gateRaw | ConvertFrom-Json

if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "spot_perp_basis_mean_reversion_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "spot_perp_basis_mean_reversion_no_funding"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        gate_status = $gate.status
        reason = "Active run gate is $($gate.status); only status/resume handling is allowed."
        next_valid_moves = @(
            "If RUNNING, wait and only do status/ETA checks.",
            "If STOPPED_INCOMPLETE, visibly resume or explicitly reject the dataset before PlanOnly branch work.",
            "Do not collect, replay, grid, paper-forward, use API keys, or place live orders."
        )
        output_path = $OutputPath
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$selectedByGate = [bool](
    ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_RESEARCH") -or
    ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_*") -or
    ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_PUBLIC_PROBE*") -or
    ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_AVAILABILITY*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding"
    )
)

if (-not $selectedByGate) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "spot_perp_basis_mean_reversion_planonly"
        decision = "BLOCKED_BY_GATE_BRANCH_MISMATCH"
        selected_branch = "spot_perp_basis_mean_reversion_no_funding"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        gate_status = $gate.status
        gate_next_goal_decision = $gate.next_goal_decision
        reason = "Gate has not selected spot_perp_basis_mean_reversion_no_funding. Run the structural branch selector first."
        next_valid_moves = @(
            "Run tools\trading_structural_branch_planonly.ps1 -UpdateGate -Json if prior branches are rejected.",
            "Do not bypass branch routing."
        )
        output_path = $OutputPath
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$python = Resolve-Python
$argsList = @($modulePath, "--repo-root", $repoRoot, "--out", $OutputPath)
if ($DailyRunDir) {
    $argsList += @("--daily-run-dir", $DailyRunDir)
}
$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "spot_perp_basis_mean_reversion.py failed with exit code $LASTEXITCODE"
}
$result = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json

Set-JsonProperty -Object $result -Name "gate_status" -Value $gate.status
Set-JsonProperty -Object $result -Name "gate_next_goal_decision_before" -Value $gate.next_goal_decision
Set-JsonProperty -Object $result -Name "gate_updated" -Value $false
Set-JsonProperty -Object $result -Name "commands" -Value ([ordered]@{
    rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
    rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
    active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
})

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $nextDecision = [string]$result.decision
    $nextStep = if ($nextDecision -eq "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_BACKTEST_SCAFFOLD") {
        "Build read-only spot/perp basis detector/backtester PlanOnly on verified paired spot/perp history. Do not run collect/grid/live/API/paper-forward."
    } else {
        "Build spot/perp basis public-data availability preflight PlanOnly: paired spot mid, perp mark/mid, spread/depth and funding-regime fields. Do not start collect/grid/live/API/paper-forward."
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $nextDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "spot_perp_basis_mean_reversion_no_funding PlanOnly scaffold is built. Funding payout is excluded from PnL; paired spot/perp data and hedge feasibility must pass preflight before any backtest or collect."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "spot_perp_basis_mean_reversion_no_funding"
        verdict = if ($nextDecision -eq "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_BACKTEST_SCAFFOLD") { "planonly_scaffold_ready_for_backtest_scaffold" } else { "planonly_scaffold_ready_for_availability_preflight" }
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "listing_event_drift_reversal"
        previous_verdict = "replay_planonly_rejected"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_branch_required = $false
        next_step_required = if ($nextDecision -eq "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_BACKTEST_SCAFFOLD") { "build_spot_perp_basis_detector_backtester_planonly" } else { "build_spot_perp_basis_availability_preflight_planonly" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_mean_reversion_planonly_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_mean_reversion_planonly_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_spot_perp_basis_mean_reversion_planonly_decision" -Value $nextDecision
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    Set-JsonProperty -Object $result -Name "gate_updated" -Value $true
}

Save-Result -Payload $result
