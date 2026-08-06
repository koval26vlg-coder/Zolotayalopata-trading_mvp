param(
    [string]$FixedV1Path = "",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_replay_v1.py"
$readyDecision = "SLOW_LIQUIDITY_FIXED_V1_PLANONLY_READY_FOR_REPLAY_VALIDATION"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\slow_liquidity_fixed_v1_replay_planonly_$timestamp.json"
}

function Resolve-RepoPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
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

    Write-Host "Slow-liquidity fixed v1 replay PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Trades: $($Payload.summary.trades)"
    Write-Host "Net PnL: $($Payload.summary.total_net_pnl_quote)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "slow_liquidity_fixed_v1_replay_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "slow_liquidity_regime_breakout_retest"
        would_start = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
        output_path = $OutputPath
    }
    Save-Result -Payload $blocked
    exit 0
}

$gateDoc = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { $null }
if (-not $FixedV1Path -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_fixed_v1_plan_output_path) {
    $FixedV1Path = [string]$gateDoc.last_slow_liquidity_fixed_v1_plan_output_path
}

$FixedV1Path = Resolve-RepoPath $FixedV1Path
$OutputPath = Resolve-RepoPath $OutputPath
foreach ($requiredPath in @($FixedV1Path, $modulePath)) {
    if (-not $requiredPath -or -not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath"
    }
}

$gateAllowsReplay = [bool](
    ([string]$gate.next_goal_decision -eq $readyDecision) -and
    [bool]$gate.replay_allowed -and
    -not [bool]$gate.grid_allowed
)
if (-not $gateAllowsReplay) {
    throw "slow-liquidity fixed v1 replay is not the active gate step. decision=$($gate.next_goal_decision), replay_allowed=$($gate.replay_allowed), grid_allowed=$($gate.grid_allowed)"
}

$pythonCandidates = @(
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = $pythonCmd.Source
    }
}
if (-not $python) {
    throw "Python runtime not found."
}

$raw = & $python $modulePath --fixed-v1 $FixedV1Path --output $OutputPath
if ($LASTEXITCODE -ne 0) {
    throw "slow_liquidity_replay_v1.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $candidate = [bool]$result.research_acceptance.robust_candidate
    $nextStep = if ($candidate) {
        "Run independent review of fixed slow-liquidity v1 replay artifact. Do not start paper-forward/live/API/grid."
    } else {
        "Reject slow_liquidity fixed v1 on replay evidence and select another structural PlanOnly branch. Do not tune parameters after replay."
    }
    $verdict = if ($candidate) {
        "fixed_v1_replay_candidate_requires_independent_review"
    } else {
        "fixed_v1_replay_rejected_no_robust_edge"
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "fixed slow-liquidity v1 replay PlanOnly completed. trades=$($result.summary.trades), net_pnl=$($result.summary.total_net_pnl_quote), expectancy=$($result.summary.expectancy_quote), robust_candidate=$candidate."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_replay_v1_at" -Value ([string]$result.generated_at)
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_replay_v1_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_replay_v1_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        trades = [int]$result.summary.trades
        net_pnl_quote = [double]$result.summary.total_net_pnl_quote
        expectancy_quote = [double]$result.summary.expectancy_quote
        win_rate = [double]$result.summary.win_rate
        robust_candidate = $candidate
        next_step_required = if ($candidate) { "independent_review_before_paper_forward" } else { "select_next_structural_branch_planonly" }
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

Save-Result -Payload $result
