param(
    [string]$CalendarPath = "",
    [string]$DataQualityOutputPath = "",
    [string]$OutputPath = "",
    [string]$RunId = "",
    [string]$Quote = "USDT",
    [int]$TargetEvents = 120,
    [int]$TargetBasesMin = 30,
    [int]$PreWindowSec = 3600,
    [int]$PostWindowSec = 259200,
    [int]$MaxEventsPerBase = 2,
    [double]$MaxExchangeFraction = 0.60,
    [int]$MinExchangeCount = 2,
    [int]$CandlesPerRequest = 1000,
    [double]$RequestRatePerSec = 2.0,
    [string]$Granularities = "1m,5m,1h",
    [string]$AvailabilityPreflightPath = "",
    [switch]$UseAvailabilityOkEvents,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\listing_event_history_collect_plan.py"

if (-not $CalendarPath) {
    $CalendarPath = Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.csv"
}
if (-not $RunId) {
    $RunId = "listing_event_history_collect_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot ("exports\trading-mvp\analysis\listing_event_history_collect_preview_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
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
$rawGate = $null
if (Test-Path -LiteralPath $gatePath) {
    $rawGate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
}
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "listing_event_history_collect_preview_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        would_start = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
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

if (-not (Test-Path -LiteralPath $CalendarPath)) {
    throw "Calendar path not found: $CalendarPath"
}
if (-not $DataQualityOutputPath) {
    if ($gate.PSObject.Properties.Name -contains "last_listing_event_history_data_quality_output_path") {
        $candidateQualityPath = [string]$gate.last_listing_event_history_data_quality_output_path
        if ($candidateQualityPath -and (Test-Path -LiteralPath $candidateQualityPath)) {
            $DataQualityOutputPath = $candidateQualityPath
        }
    }
    if (-not $DataQualityOutputPath) {
        $candidateQuality = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "listing_event_history_data_quality_*.json" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($candidateQuality) {
            $DataQualityOutputPath = $candidateQuality.FullName
        }
    }
}

if (-not $AvailabilityPreflightPath) {
    if ($gate.PSObject.Properties.Name -contains "last_listing_event_history_availability_preflight_output_path") {
        $candidateAvailabilityPath = [string]$gate.last_listing_event_history_availability_preflight_output_path
        if ($candidateAvailabilityPath -and (Test-Path -LiteralPath $candidateAvailabilityPath)) {
            $AvailabilityPreflightPath = $candidateAvailabilityPath
        }
    }
    if (-not $AvailabilityPreflightPath -and $rawGate -and ($rawGate.PSObject.Properties.Name -contains "last_listing_event_history_availability_preflight_output_path")) {
        $candidateAvailabilityPath = [string]$rawGate.last_listing_event_history_availability_preflight_output_path
        if ($candidateAvailabilityPath -and (Test-Path -LiteralPath $candidateAvailabilityPath)) {
            $AvailabilityPreflightPath = $candidateAvailabilityPath
        }
    }
    if (-not $AvailabilityPreflightPath) {
        $candidateAvailability = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "listing_event_history_availability_preflight_*.json" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($candidateAvailability) {
            $AvailabilityPreflightPath = $candidateAvailability.FullName
        }
    }
}
if ($UseAvailabilityOkEvents -and $AvailabilityPreflightPath -and (Test-Path -LiteralPath $AvailabilityPreflightPath)) {
    $availability = Get-Content -Raw -LiteralPath $AvailabilityPreflightPath | ConvertFrom-Json
    if ([string]$availability.decision -ne "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET") {
        throw "Availability preflight is not accepted: $AvailabilityPreflightPath decision=$($availability.decision)"
    }
    if ($availability.probe_contract -and $availability.probe_contract.granularities) {
        $Granularities = (@($availability.probe_contract.granularities) | ForEach-Object { [string]$_ }) -join ","
    }
}
if (-not $UseAvailabilityOkEvents -and $AvailabilityPreflightPath -and (Test-Path -LiteralPath $AvailabilityPreflightPath)) {
    $availabilityForDecision = Get-Content -Raw -LiteralPath $AvailabilityPreflightPath | ConvertFrom-Json
    if ([string]$availabilityForDecision.decision -eq "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET") {
        $UseAvailabilityOkEvents = $true
        if ($availabilityForDecision.probe_contract -and $availabilityForDecision.probe_contract.granularities) {
            $Granularities = (@($availabilityForDecision.probe_contract.granularities) | ForEach-Object { [string]$_ }) -join ","
        }
    }
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
    "--calendar", $CalendarPath,
    "--output", $OutputPath,
    "--run-id", $RunId,
    "--quote", $Quote,
    "--target-events", $TargetEvents,
    "--target-bases-min", $TargetBasesMin,
    "--pre-window-sec", $PreWindowSec,
    "--post-window-sec", $PostWindowSec,
    "--max-events-per-base", $MaxEventsPerBase,
    "--max-exchange-fraction", $MaxExchangeFraction,
    "--min-exchange-count", $MinExchangeCount,
    "--candles-per-request", $CandlesPerRequest,
    "--request-rate-per-sec", $RequestRatePerSec,
    "--granularities", $Granularities
)
if ($DataQualityOutputPath) {
    $argsList += @("--previous-quality-report", $DataQualityOutputPath)
}
if ($AvailabilityPreflightPath) {
    $argsList += @("--availability-preflight", $AvailabilityPreflightPath)
}
if ($UseAvailabilityOkEvents) {
    $argsList += @("--use-availability-ok-events")
}
if ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN") {
    $argsList += @("--require-two-venue-history-preflight")
}

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "listing_event_history_collect_plan.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $qualityBlocked = $decision -eq "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_BLOCKED_NEEDS_REVISED_TWO_VENUE_PREFLIGHT"
    $gateDecision = if ($qualityBlocked) { "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN" } else { $decision }
    $nextStep = if ($qualityBlocked) {
        "Revise listing-event history collect preview with symbol-history preflight and two-venue coverage estimation. Do not start actual collect/grid/replay/live/API/paper-forward."
    } elseif ($decision -eq "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL") {
        "Await explicit user approval before implementing/running visible public OHLCV history collect. Do not start collect/grid/replay/live/API/paper-forward automatically."
    } else {
        "Fix listing-event history collect preview event diversity before any collection/replay."
    }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $gateDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Listing-event OHLCV history collect preview built: selected_events=$($result.selection.selected_events), selected_unique_bases=$($result.selection.selected_unique_bases), estimated_total_requests=$($result.request_budget.estimated_total_requests)."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_approval" -Value $null
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = if ($qualityBlocked) { "history_quality_rejected" } elseif ($decision -eq "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL") { "history_collect_preview_ready_awaiting_explicit_approval" } else { "history_collect_preview_blocked" }
        decision_source = $OutputPath
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
        next_step_required = if ($qualityBlocked) { "revise_listing_event_history_collect_preview_planonly" } else { "explicit_user_approval_before_visible_listing_event_history_collect" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_collect_preview_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_collect_preview_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_collect_preview_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_collect_preview_selected_events" -Value ([int]$result.selection.selected_events)
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_collect_preview_estimated_requests" -Value ([int]$result.request_budget.estimated_total_requests)
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 14
    exit 0
}

Write-Host "Listing event OHLCV history collect preview" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Would start: $($result.would_start)"
Write-Host "Selected events: $($result.selection.selected_events)"
Write-Host "Selected bases: $($result.selection.selected_unique_bases)"
Write-Host "Estimated requests: $($result.request_budget.estimated_total_requests)"
Write-Host "Estimated candles: $($result.request_budget.estimated_total_candles)"
Write-Host "Output: $OutputPath"
Write-Host ""
Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in @($result.next_valid_moves)) {
    Write-Host "  - $move"
}
