param(
    [string]$InputJsonl = "",
    [string]$ManifestPath = "",
    [string]$OutputPath = "",
    [int]$MinOkRows = 1000,
    [int]$MinOkEvents = 30,
    [int]$MinOkBases = 20,
    [int]$MinOkExchanges = 2,
    [int]$MinOkEventGranularitySlots = 30,
    [double]$MinOkEventFraction = 0.25,
    [double]$MinOkSlotFraction = 0.20,
    [double]$MaxApiErrorSlotRate = 0.50,
    [double]$MaxSingleExchangeOkEventFraction = 0.70,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\listing_event_history_quality.py"

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

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return (Join-Path $repoRoot $PathValue)
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "listing_event_history_data_quality"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        accepted = $false
        replay_allowed = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
    }
    if ($Json) {
        $blocked | ConvertTo-Json -Depth 10
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
}

$rawGate = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { $null }
if (-not $InputJsonl) {
    if ($rawGate -and [string]$rawGate.last_listing_event_history_collect_output_path) {
        $InputJsonl = [string]$rawGate.last_listing_event_history_collect_output_path
    } elseif ($rawGate -and [string]$rawGate.output_path) {
        $InputJsonl = [string]$rawGate.output_path
    } elseif ($gate.output -and [string]$gate.output.path) {
        $InputJsonl = [string]$gate.output.path
    }
}
if (-not $ManifestPath) {
    if ($rawGate -and [string]$rawGate.last_listing_event_history_collect_manifest_path) {
        $ManifestPath = [string]$rawGate.last_listing_event_history_collect_manifest_path
    } elseif ($rawGate -and [string]$rawGate.manifest_path) {
        $ManifestPath = [string]$rawGate.manifest_path
    } elseif ([string]$gate.manifest_path) {
        $ManifestPath = [string]$gate.manifest_path
    }
}
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_history_data_quality_$timestamp.json"
}

if (-not $InputJsonl) {
    throw "InputJsonl is required and could not be inferred from active gate."
}
if (-not $ManifestPath) {
    throw "ManifestPath is required and could not be inferred from active gate."
}
$InputJsonl = Resolve-RepoPath $InputJsonl
$ManifestPath = Resolve-RepoPath $ManifestPath
$OutputPath = Resolve-RepoPath $OutputPath

if (-not (Test-Path -LiteralPath $InputJsonl)) {
    throw "InputJsonl not found: $InputJsonl"
}
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "ManifestPath not found: $ManifestPath"
}

$pythonCandidates = @(
    $env:TRADING_MVP_PYTHON,
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
) | Where-Object { $_ }
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
    "--input-jsonl", $InputJsonl,
    "--manifest", $ManifestPath,
    "--output", $OutputPath,
    "--min-ok-rows", $MinOkRows,
    "--min-ok-events", $MinOkEvents,
    "--min-ok-bases", $MinOkBases,
    "--min-ok-exchanges", $MinOkExchanges,
    "--min-ok-event-granularity-slots", $MinOkEventGranularitySlots,
    "--min-ok-event-fraction", $MinOkEventFraction,
    "--min-ok-slot-fraction", $MinOkSlotFraction,
    "--max-api-error-slot-rate", $MaxApiErrorSlotRate,
    "--max-single-exchange-ok-event-fraction", $MaxSingleExchangeOkEventFraction
)

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "listing_event_history_quality.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $accepted = [bool]$result.accepted
    $nextStep = if ($accepted) {
        "Run guarded listing-event normalizer on accepted history quality. Do not run replay/grid/live/API/paper-forward until normalizer sets replay_allowed=true."
    } else {
        "Do not replay/grid. Revise listing-event history collection plan: improve Gate historical coverage or resample events with two-venue OK coverage while retaining no-data/delisted outcomes."
    }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value ([string]$result.decision)
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Listing-event history data-quality accepted=$accepted; ok_events=$($result.metrics.ok_events), ok_bases=$($result.metrics.ok_bases), ok_exchanges=$($result.metrics.ok_exchanges), api_error_slot_rate=$($result.metrics.api_error_slot_rate)."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_data_quality_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_data_quality_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_data_quality_decision" -Value ([string]$result.decision)
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_data_quality_reasons" -Value @($result.reasons)
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = if ($accepted) { "history_quality_accepted_ready_for_normalizer" } else { "history_quality_rejected" }
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "cross_venue_spot_dislocation_inventory_rebalance"
        previous_verdict = "rejected_no_net_edge_after_base_fees"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        data_quality_accepted = $accepted
        data_quality_reasons = @($result.reasons)
        next_step_required = if ($accepted) { "run_listing_event_normalizer_on_history" } else { "revise_listing_event_history_collect_plan" }
    })
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 14
    exit 0
}

Write-Host "Listing-event history data-quality" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Accepted: $($result.accepted)"
Write-Host "Reasons: $(@($result.reasons) -join ', ')"
Write-Host "OK events/bases/exchanges: $($result.metrics.ok_events) / $($result.metrics.ok_bases) / $($result.metrics.ok_exchanges)"
Write-Host "OK rows: $($result.metrics.ok_rows)"
Write-Host "API error slot rate: $($result.metrics.api_error_slot_rate)"
Write-Host "Output: $OutputPath"
