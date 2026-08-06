param(
    [string]$RunDir = "",
    [string]$ReportPath = "",
    [string]$OutputPath = "",
    [double]$MaxDrawdownPct = 25.0,
    [double]$MaxTopBaseShare = 0.25,
    [int]$MinOosRebalances = 20,
    [double]$MinRollingWfPositiveRatio = 0.60,
    [int]$MinHistoryDays = 120,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$module = Join-Path $repoRoot "trading_mvp\src\momentum_survivorship_audit.py"

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

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        mode = "trading_daily_momentum_survivorship_audit"
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        reason = "Active run gate is $($gate.status); only compliant status/resume work is allowed."
        would_start = $false
        research_only = $true
        strategy_accepted = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        grid_search = $false
        paper_forward_allowed = $false
    }
    if ($Json) {
        $blocked | ConvertTo-Json -Depth 8
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
}

$rawGate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if (-not $RunDir) {
    $RunDir = Join-Path $repoRoot "exports\trading-mvp\daily\daily_collect_20260702_top200"
}
if (-not $ReportPath) {
    if ($rawGate.PSObject.Properties.Name -contains "last_daily_momentum_backtest_output_path" -and $rawGate.last_daily_momentum_backtest_output_path) {
        $ReportPath = [string]$rawGate.last_daily_momentum_backtest_output_path
    } else {
        $latestReport = Get-ChildItem -LiteralPath (Join-Path $repoRoot "exports\trading-mvp\backtests") -Filter "momentum_daily_*.json" -File |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($latestReport) {
            $ReportPath = $latestReport.FullName
        }
    }
}
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\cross_sectional_momentum_survivorship_audit_$timestamp.json"
}

if (-not (Test-Path -LiteralPath $RunDir)) {
    throw "RunDir not found: $RunDir"
}
if (-not (Test-Path -LiteralPath $ReportPath)) {
    throw "ReportPath not found: $ReportPath"
}

$pythonCandidates = @(
    "C:\Program Files\Python313\python.exe",
    "py",
    "python"
)
$python = $pythonCandidates | Where-Object {
    if ($_ -like "*\*") {
        Test-Path -LiteralPath $_
    } else {
        [bool](Get-Command $_ -ErrorAction SilentlyContinue)
    }
} | Select-Object -First 1
if (-not $python) {
    throw "No Python runtime found. Tried: $($pythonCandidates -join ', ')"
}

$raw = & $python $module `
    --run-dir $RunDir `
    --report $ReportPath `
    --output $OutputPath `
    --max-drawdown-pct $MaxDrawdownPct `
    --max-top-base-share $MaxTopBaseShare `
    --min-oos-rebalances $MinOosRebalances `
    --min-rolling-wf-positive-ratio $MinRollingWfPositiveRatio `
    --min-history-days $MinHistoryDays
if ($LASTEXITCODE -ne 0) {
    throw "momentum_survivorship_audit failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value ([string]$result.decision)
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value ("daily momentum survivorship/risk audit completed. survivorship_pass=$($result.summary.survivorship_pass); history_pass=$($result.summary.history_pass); risk_policy_pass=$($result.summary.risk_policy_pass). Strategy remains not accepted.")
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Resolve survivorship/point-in-time universe bias before any paper-forward/live/API/grid. If no point-in-time/delisted universe can be sourced, mark daily momentum acceptance as blocked/rejected and choose a new hypothesis."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $gateDoc.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "cross_sectional_momentum_daily"
        verdict = if ([string]$result.decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_READY_FOR_INDEPENDENT_REVIEW") { "survivorship_audit_ready_for_independent_review" } else { "survivorship_audit_revise_required" }
        decision_source = $OutputPath
        selected_at = $result.generated_at
        strategy_accepted = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = "resolve_survivorship_point_in_time_universe_bias"
    })
    Set-JsonProperty -Object $gateDoc -Name "last_daily_momentum_survivorship_audit_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_daily_momentum_survivorship_audit_decision" -Value ([string]$result.decision)
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    $gateDoc | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 20
    exit 0
}

Write-Host "Daily Momentum Survivorship Audit" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Output: $OutputPath"
Write-Host "Survivorship pass: $($result.summary.survivorship_pass)"
Write-Host "History pass: $($result.summary.history_pass)"
Write-Host "Risk policy pass: $($result.summary.risk_policy_pass)"
