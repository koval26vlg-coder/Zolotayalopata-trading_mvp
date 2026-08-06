param(
    [string]$ScreenPath = "",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\pit_cross_venue_evidence_gap.py"
$analysisRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis"
$expectedDecision = "PIT_LINEAR_PERP_SCREEN_COMPLETED_CANDIDATES_REQUIRE_DEEPER_EVIDENCE_PLANONLY"

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param($Object, [string]$Path)
    $temp = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 35 | Set-Content -LiteralPath $temp -Encoding UTF8
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
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

$status = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$status.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    throw "Active run gate is $($status.status); evidence-gap analysis is blocked."
}
$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if ([string]$gate.next_goal_decision -ne $expectedDecision) {
    throw "Evidence-gap PlanOnly is not the current step: $($gate.next_goal_decision)"
}
if ([bool]$gate.replay_allowed) {
    throw "Fail-closed guard: replay_allowed must remain false."
}
if ([string]::IsNullOrWhiteSpace($ScreenPath)) {
    $ScreenPath = [string]$gate.last_pit_linear_perp_screen_output_path
}
$ScreenPath = (Resolve-Path -LiteralPath $ScreenPath).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    New-Item -ItemType Directory -Force -Path $analysisRoot | Out-Null
    $OutputPath = Join-Path $analysisRoot ("pit_linear_perp_cross_venue_evidence_gap_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
}
$python = Resolve-Python
& $python $modulePath --screen $ScreenPath --out $OutputPath | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
    throw "PIT evidence-gap module failed with exit code $LASTEXITCODE"
}
$result = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json

if ($UpdateGate) {
    $nextDecision = if ([string]$result.decision -eq "PIT_LINEAR_PERP_SCREEN_EVIDENCE_GAP_REJECTED_NO_RAW_EDGE") {
        "PIT_LINEAR_PERP_SCREEN_REJECTED_SELECT_NEXT_HYPOTHESIS_PLANONLY"
    } else {
        "PIT_LINEAR_PERP_CONTRACT_IDENTITY_DEPTH_FUNDING_AVAILABILITY_PREFLIGHT_PLANONLY_REQUIRED"
    }
    $nextStep = if ($nextDecision -eq "PIT_LINEAR_PERP_SCREEN_REJECTED_SELECT_NEXT_HYPOTHESIS_PLANONLY") {
        "Select a new structural hypothesis PlanOnly. Keep replay/grid/paper/live/API blocked."
    } else {
        "Build a no-network PlanOnly availability preflight for contract identity/multiplier, executable depth, exact quote timestamps and funding. Raw observations are not valid candidates."
    }
    Set-JsonProperty $gate "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gate "next_goal_decision" $nextDecision
    Set-JsonProperty $gate "next_goal_reason" ([string]$result.decision)
    Set-JsonProperty $gate "next_step_after_ready" $nextStep
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" $nextStep
    Set-JsonProperty $gate "last_pit_linear_perp_evidence_gap_output_path" $OutputPath
    Set-JsonProperty $gate "last_pit_linear_perp_evidence_gap_decision" ([string]$result.decision)
    Set-JsonProperty $gate "last_pit_linear_perp_validated_candidate_events" ([int]$result.validated_candidates.events)
    Set-JsonProperty $gate "last_pit_linear_perp_top1_concentration" $result.concentration.top_1_share
    Set-JsonProperty $gate "last_pit_linear_perp_identity_collision_indicator" ([bool]$result.diagnostics.identity_collision_indicator)
    foreach ($name in @("replay_allowed", "grid_allowed", "backtest_allowed", "paper_forward_allowed", "live_orders", "api_keys", "leverage_or_margin", "materialization_allowed", "collect_allowed")) {
        Set-JsonProperty $gate $name $false
    }
    Set-JsonProperty $gate "strategy_branch_status" ([ordered]@{
        branch = "pit_linear_perp_cross_venue_screening"
        verdict = if ([int]$result.raw_observations.cost_positive_events -gt 0) { "raw_observations_blocked_unvalidated_identity_depth_funding" } else { "rejected_no_raw_edge_after_base_costs" }
        source_contract_type = "linear_perp"
        supports_spot_objective = $false
        raw_cost_positive_observations = [int]$result.raw_observations.cost_positive_events
        validated_candidate_events = 0
        strategy_accepted = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = [string]$result.next_valid_move
    })
    Write-JsonAtomic $gate $gatePath
}

if ($Json) {
    $result | ConvertTo-Json -Depth 20
    exit 0
}
Write-Host "PIT Linear-Perp Evidence Gap" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Raw observations: $($result.raw_observations.cost_positive_events)"
Write-Host "Validated candidates: $($result.validated_candidates.events)"
Write-Host "Output: $OutputPath"
