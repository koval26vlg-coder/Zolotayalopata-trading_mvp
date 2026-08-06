param(
    [string]$ScreenPath = "",
    [string]$EvidenceGapPath = "",
    [string]$FeeEvidenceDir = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\fee_evidence_20260702",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\pit_cross_venue_availability.py"
$analysisRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis"
$expectedDecision = "PIT_LINEAR_PERP_CONTRACT_IDENTITY_DEPTH_FUNDING_AVAILABILITY_PREFLIGHT_PLANONLY_REQUIRED"

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Write-JsonAtomic {
    param($Object, [string]$Path)
    $temp = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-Python {
    foreach ($candidate in @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

$status = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$status.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    throw "Active run gate is $($status.status); availability preflight is blocked."
}
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]$gate.next_goal_decision -ne $expectedDecision) {
    throw "Availability preflight is not the current step: $($gate.next_goal_decision)"
}
if ([bool]$gate.replay_allowed) { throw "Fail-closed guard: replay_allowed must remain false." }
if ([string]::IsNullOrWhiteSpace($ScreenPath)) { $ScreenPath = [string]$gate.last_pit_linear_perp_screen_output_path }
if ([string]::IsNullOrWhiteSpace($EvidenceGapPath)) { $EvidenceGapPath = [string]$gate.last_pit_linear_perp_evidence_gap_output_path }
$ScreenPath = (Resolve-Path -LiteralPath $ScreenPath).Path
$EvidenceGapPath = (Resolve-Path -LiteralPath $EvidenceGapPath).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    New-Item -ItemType Directory -Force -Path $analysisRoot | Out-Null
    $OutputPath = Join-Path $analysisRoot ("pit_linear_perp_cross_venue_availability_preflight_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
}
$python = Resolve-Python
& $python $modulePath --screen $ScreenPath --evidence-gap $EvidenceGapPath --fee-evidence-dir $FeeEvidenceDir --out $OutputPath | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
    throw "PIT availability preflight failed with exit code $LASTEXITCODE"
}
$result = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json

if ($UpdateGate) {
    $nextDecision = "PIT_LINEAR_PERP_CURRENT_DATASET_REJECTED_CHOOSE_FOCUSED_FORWARD_OOS_OR_NEW_HYPOTHESIS_PLANONLY"
    $nextStep = "Current 24h PIT dataset is rejected for edge validation. PlanOnly decision only: either seal discovery and design a focused visible forward-OOS collector approval packet, or reject the branch and select a new hypothesis. No collect starts automatically."
    Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gate "next_goal_decision" $nextDecision
    Set-JsonProperty $gate "next_goal_reason" ([string]$result.decision)
    Set-JsonProperty $gate "next_step_after_ready" $nextStep
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" $nextStep
    Set-JsonProperty $gate "last_pit_linear_perp_availability_output_path" $OutputPath
    Set-JsonProperty $gate "last_pit_linear_perp_availability_decision" ([string]$result.decision)
    Set-JsonProperty $gate "last_pit_linear_perp_historical_retrofit_possible" ([bool]$result.historical_retrofit_possible)
    Set-JsonProperty $gate "last_pit_linear_perp_static_metadata_both_venues_bases" @($result.metadata_coverage.both_venues_bases)
    Set-JsonProperty $gate "screening_allowed" $false
    foreach ($name in @("replay_allowed", "grid_allowed", "backtest_allowed", "paper_forward_allowed", "live_orders", "api_keys", "leverage_or_margin", "materialization_allowed", "collect_allowed")) {
        Set-JsonProperty $gate $name $false
    }
    Set-JsonProperty $gate "strategy_branch_status" ([ordered]@{
        branch = "pit_linear_perp_cross_venue_screening"
        verdict = "current_dataset_rejected_for_edge_validation_missing_historical_evidence"
        raw_cost_positive_observations = [int]$result.raw_observations.events
        validated_candidate_events = 0
        historical_retrofit_possible = $false
        strategy_accepted = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = "planonly_choose_focused_forward_oos_or_new_hypothesis"
    })
    Write-JsonAtomic $gate $gatePath
}

if ($Json) { $result | ConvertTo-Json -Depth 25; exit 0 }
Write-Host "PIT Linear-Perp Availability Preflight" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Historical retrofit possible: $($result.historical_retrofit_possible)"
Write-Host "Validated candidates: $($result.validated_candidates.events)"
Write-Host "Output: $OutputPath"
