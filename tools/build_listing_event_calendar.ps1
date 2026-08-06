param(
    [string]$OutputPath = "",
    [string]$SummaryPath = "",
    [string]$UniversePath = "",
    [string]$Quote = "USDT",
    [int]$TimeoutSec = 20,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\listing_calendar.py"

if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.csv"
}
if (-not $SummaryPath) {
    $SummaryPath = [System.IO.Path]::ChangeExtension($OutputPath, ".summary.json")
}
if (-not $UniversePath) {
    $candidate = Join-Path $repoRoot "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv"
    if (Test-Path -LiteralPath $candidate) {
        $UniversePath = $candidate
    }
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

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "listing_event_calendar_build"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        would_start = $false
        collect_allowed_now = $false
        grid_allowed_now = $false
        replay_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
    }
    if ($Json) {
        $blocked | ConvertTo-Json -Depth 8
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
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

$argsList = @(
    $modulePath,
    "--output", $OutputPath,
    "--summary", $SummaryPath,
    "--quote", $Quote,
    "--timeout-sec", $TimeoutSec
)
if ($UniversePath) {
    $argsList += @("--universe", $UniversePath)
}

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "listing_calendar.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = if ([bool]$result.bias_control_pass) {
        "LISTING_EVENT_CALENDAR_BIAS_CONTROL_PASS_READY_FOR_NORMALIZER"
    } else {
        "LISTING_EVENT_CALENDAR_PARTIAL_NEEDS_DELISTED_OR_NONTRADABLE_COVERAGE"
    }
    $reason = if ([bool]$result.bias_control_pass) {
        "Listing event calendar has enough two-venue timestamped events and delisted/non-tradable coverage for a read-only event normalizer/backtester PlanOnly."
    } else {
        "Listing event calendar was built from official public API snapshots, but it is not bias-controlled enough: delisted/frozen/no-trade coverage is missing or weak. Do not backtest yet."
    }
    $nextStep = if ([bool]$result.bias_control_pass) {
        "Implement read-only listing_event_drift_reversal event normalizer/backtester PlanOnly. Do not start collect/grid/live/API/paper-forward."
    } else {
        "Add delisted/frozen/no-trade listing-event source before any backtest. Current calendar is a useful API snapshot but not bias-controlled proof data."
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value $reason
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = if ([bool]$result.bias_control_pass) { "calendar_bias_control_pass_ready_for_normalizer" } else { "calendar_partial_needs_delisted_or_nontradable_coverage" }
        decision_source = $SummaryPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "cross_venue_spot_dislocation_inventory_rebalance"
        previous_verdict = "rejected_no_net_edge_after_base_fees"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_branch_required = $false
        next_step_required = [string]$result.required_next_step
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_calendar_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_calendar_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_calendar_summary_path" -Value $SummaryPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_calendar_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_calendar_rows" -Value ([int]$result.rows)
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_calendar_bias_control_pass" -Value ([bool]$result.bias_control_pass)
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
    exit 0
}

Write-Host "Listing event calendar build" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Rows: $($result.rows)"
Write-Host "Timestamp coverage: $([Math]::Round([double]$result.timestamp_coverage, 3))"
Write-Host "Bias control pass: $($result.bias_control_pass)"
Write-Host "Output: $OutputPath"
Write-Host "Summary: $SummaryPath"
