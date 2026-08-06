param(
    [string]$PreviewPath = "",
    [string]$DataQualityOutputPath = "",
    [string]$OutputPath = "",
    [int]$MaxEventsPerExchange = 8,
    [string]$Granularities = "5m",
    [int]$CandlesPerRequest = 100,
    [int]$TimeoutSec = 10,
    [int]$MaxRetries = 1,
    [double]$SleepSec = 0.0,
    [int]$ProbeWindowSec = 3600,
    [switch]$ConfirmedPublicProbe,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\listing_event_history_availability_preflight.py"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_history_availability_preflight_$timestamp.json"
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
        mode = "listing_event_history_availability_preflight"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        would_start_collect = $false
        would_run_public_probe = $false
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
        $blocked | ConvertTo-Json -Depth 10
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
}

if (-not $PreviewPath) {
    if ($gate.PSObject.Properties.Name -contains "last_listing_event_history_collect_preview_output_path") {
        $candidatePreviewPath = [string]$gate.last_listing_event_history_collect_preview_output_path
        if ($candidatePreviewPath -and (Test-Path -LiteralPath $candidatePreviewPath)) {
            $PreviewPath = $candidatePreviewPath
        }
    }
    if (-not $PreviewPath -and $gate.PSObject.Properties.Name -contains "preview_path") {
        $candidatePreviewPath = [string]$gate.preview_path
        if ($candidatePreviewPath -and (Test-Path -LiteralPath $candidatePreviewPath)) {
            $PreviewPath = $candidatePreviewPath
        }
    }
    if (-not $PreviewPath) {
        $candidatePreview = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "listing_event_history_collect_preview_*.json" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($candidatePreview) {
            $PreviewPath = $candidatePreview.FullName
        }
    }
}
if (-not $PreviewPath -or -not (Test-Path -LiteralPath $PreviewPath)) {
    throw "Preview path not found: $PreviewPath"
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
    "--preview", $PreviewPath,
    "--output", $OutputPath,
    "--repo-root", $repoRoot,
    "--max-events-per-exchange", $MaxEventsPerExchange,
    "--granularities", $Granularities,
    "--candles-per-request", $CandlesPerRequest,
    "--timeout-sec", $TimeoutSec,
    "--max-retries", $MaxRetries,
    "--sleep-sec", $SleepSec,
    "--probe-window-sec", $ProbeWindowSec
)
if ($DataQualityOutputPath) {
    $argsList += @("--previous-quality-report", $DataQualityOutputPath)
}
if ($ConfirmedPublicProbe) {
    $argsList += @("--probe")
}

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "listing_event_history_availability_preflight.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $nextStep = switch ($decision) {
        "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE" {
            "Await explicit confirmation to run a short visible public REST availability probe. Do not start actual OHLCV collect/grid/replay/live/API/paper-forward."
        }
        "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" {
            "Build revised listing-event history collect approval packet using accepted two-venue preflight. Do not start actual collect without explicit approval."
        }
        default {
            "Resample/expand listing events or fix Gate endpoint mapping before any actual collect/grid/replay/live/API/paper-forward."
        }
    }
    $gateDecision = switch ($decision) {
        "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE" { "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE" }
        "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" { "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" }
        default { "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_RESAMPLE_OR_GATE_FIX" }
    }
    $verdict = switch ($gateDecision) {
        "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE" { "history_availability_preflight_planonly_ready" }
        "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET" { "history_availability_preflight_accepted" }
        default { "history_availability_preflight_rejected" }
    }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $gateDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Listing-event history availability preflight decision=$decision; planned_slots=$($result.probe_contract.planned_slots); ok_exchanges=$($result.summary.ok_exchanges)."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_public_probe" -Value (-not $ConfirmedPublicProbe)
    $publicProbeCommandParts = @(
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"",
        "-PreviewPath `"$PreviewPath`"",
        "-MaxEventsPerExchange $MaxEventsPerExchange",
        "-Granularities $Granularities",
        "-CandlesPerRequest $CandlesPerRequest",
        "-TimeoutSec $TimeoutSec",
        "-MaxRetries $MaxRetries",
        "-SleepSec $SleepSec",
        "-ProbeWindowSec $ProbeWindowSec",
        "-ConfirmedPublicProbe",
        "-UpdateGate",
        "-Json"
    )
    if ($DataQualityOutputPath) {
        $publicProbeCommandParts = @($publicProbeCommandParts[0], "-DataQualityOutputPath `"$DataQualityOutputPath`"") + $publicProbeCommandParts[1..($publicProbeCommandParts.Count - 1)]
    }
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_public_probe_approval" -Value ($publicProbeCommandParts -join " ")
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = $verdict
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
        next_step_required = if ($ConfirmedPublicProbe) { "build_revised_collect_approval_packet_or_resample" } else { "run_visible_confirmed_public_availability_probe" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_availability_preflight_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_availability_preflight_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_availability_preflight_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_availability_preflight_confirmed_probe" -Value ([bool]$ConfirmedPublicProbe)
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 14
    exit 0
}

Write-Host "Listing event history availability preflight" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Would run public probe: $($result.would_run_public_probe)"
Write-Host "Would start collect: $($result.would_start_collect)"
Write-Host "Planned slots: $($result.probe_contract.planned_slots)"
Write-Host "Output: $OutputPath"
Write-Host ""
Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in @($result.next_valid_moves)) {
    Write-Host "  - $move"
}
