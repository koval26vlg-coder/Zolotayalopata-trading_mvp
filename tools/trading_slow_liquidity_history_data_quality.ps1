param(
    [string]$InputJsonl = "",
    [string]$ManifestPath = "",
    [string]$OutputPath = "",
    [int]$MinOkRows = 100000,
    [int]$MinOkBases = 20,
    [int]$MinOkExchanges = 2,
    [int]$MinOkMarketGranularitySlots = 150,
    [double]$MinOkSlotFraction = 0.35,
    [double]$MaxApiErrorSlotRate = 0.70,
    [int]$MinTwoExchangeBases = 15,
    [int]$MinTwoExchangeFullCoverage1h4hBases = 8,
    [double]$MinFullCoverageRatio = 0.80,
    [ValidateRange(0, 2147483647)][int]$MaxDuplicateCandles = 0,
    [switch]$RequireOfficialIdentityAfterQuality,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_history_quality.py"
$exactRecollectRunId = "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6"
$exactRecollectQualityOutputPath = `
    "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\slow_liquidity_history_recollect_quality_20260813_pagecap_provenance_slotintegrity_v6.json"

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
        mode = "slow_liquidity_history_data_quality"
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
    if ($rawGate -and [string]$rawGate.last_slow_liquidity_history_collect_output_path) {
        $InputJsonl = [string]$rawGate.last_slow_liquidity_history_collect_output_path
    } elseif ($rawGate -and [string]$rawGate.output_path) {
        $InputJsonl = [string]$rawGate.output_path
    } elseif ($gate.output -and [string]$gate.output.path) {
        $InputJsonl = [string]$gate.output.path
    }
}
if (-not $ManifestPath) {
    if ($rawGate -and [string]$rawGate.last_slow_liquidity_history_collect_manifest_path) {
        $ManifestPath = [string]$rawGate.last_slow_liquidity_history_collect_manifest_path
    } elseif ($rawGate -and [string]$rawGate.manifest_path) {
        $ManifestPath = [string]$rawGate.manifest_path
    } elseif ([string]$gate.manifest_path) {
        $ManifestPath = [string]$gate.manifest_path
    }
}
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_history_data_quality_$timestamp.json"
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

if ($UpdateGate -and $rawGate -and
    [string]$rawGate.run_id -ceq $exactRecollectRunId) {
    throw "Exact recollect gate updates require run_exact_slow_liquidity_recollect_quality.ps1."
}
if ([System.IO.Path]::GetFullPath($OutputPath) -ieq
    [System.IO.Path]::GetFullPath($exactRecollectQualityOutputPath)) {
    throw "The exact recollect final quality report is owned by run_exact_slow_liquidity_recollect_quality.ps1."
}

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
    "--min-ok-bases", $MinOkBases,
    "--min-ok-exchanges", $MinOkExchanges,
    "--min-ok-market-granularity-slots", $MinOkMarketGranularitySlots,
    "--min-ok-slot-fraction", $MinOkSlotFraction,
    "--max-api-error-slot-rate", $MaxApiErrorSlotRate,
    "--min-two-exchange-bases", $MinTwoExchangeBases,
    "--min-two-exchange-full-coverage-1h4h-bases", $MinTwoExchangeFullCoverage1h4hBases,
    "--min-full-coverage-ratio", $MinFullCoverageRatio,
    "--max-duplicate-candles", $MaxDuplicateCandles
)

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "slow_liquidity_history_quality.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($RequireOfficialIdentityAfterQuality -and [bool]$result.accepted) {
    Set-JsonProperty -Object $result -Name "decision" -Value `
        "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL"
    Set-JsonProperty -Object $result -Name "fixed_signal_plan_allowed" -Value $false
    Set-JsonProperty -Object $result -Name "normalizer_allowed" -Value $false
    Set-JsonProperty -Object $result -Name "identity_verification_required" -Value $true
    Set-JsonProperty -Object $result -Name "identity_verification_authorized" -Value $false
    Set-JsonProperty -Object $result -Name "next_step_after_ready" -Value `
        "Request a separate exact official MEXC/Gate spot identity verification approval. Exclude unresolved or conflicting tickers; require at least eight verified bases before fixed-signal PlanOnly."
    [System.IO.File]::WriteAllText(
        $OutputPath,
        (($result | ConvertTo-Json -Depth 20) + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $accepted = [bool]$result.accepted
    $metrics = $result.metrics
    $nextStep = if ($accepted -and $RequireOfficialIdentityAfterQuality) {
        "Await separate exact approval for official MEXC/Gate spot identity verification. Do not run fixed-signal, replay, OOS, evaluator, grid, paper or live steps."
    } elseif ($accepted) {
        "Run fixed-signal PlanOnly for slow_liquidity_regime_breakout_retest on clean 1h/4h two-venue slice. Do not run replay/grid/live/API/paper-forward until fixed-signal gate passes."
    } else {
        "Do not replay/grid. Recollect or rescope slow-liquidity history to enough two-venue 1h/4h coverage before signal design."
    }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value ([string]$result.decision)
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Slow-liquidity history data-quality accepted=$accepted; ok_rows=$($metrics.ok_rows), ok_bases=$($metrics.ok_bases), ok_slots=$($metrics.ok_market_granularity_slots), two_exchange_bases=$($metrics.two_exchange_bases), clean_1h4h_two_venue_bases=$($metrics.two_exchange_full_coverage_1h4h_bases), api_error_slot_rate=$($metrics.api_error_slot_rate)."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "identity_verification_required" -Value `
        ([bool]($accepted -and $RequireOfficialIdentityAfterQuality))
    Set-JsonProperty -Object $gateDoc -Name "identity_verification_authorized" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_quality_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_quality_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_quality_decision" -Value ([string]$result.decision)
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_quality_reasons" -Value @($result.reasons)
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_quality_warnings" -Value @($result.warnings)
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = if ($accepted -and $RequireOfficialIdentityAfterQuality) {
            "history_quality_accepted_await_official_identity_approval"
        } elseif ($accepted) {
            "history_quality_accepted_ready_for_fixed_signal_planonly"
        } else {
            "history_quality_rejected"
        }
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "spot_perp_basis_or_listing_event"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        data_quality_accepted = $accepted
        data_quality_reasons = @($result.reasons)
        data_quality_warnings = @($result.warnings)
        clean_1h4h_two_venue_bases = $metrics.two_exchange_full_coverage_1h4h_bases
        next_step_required = if ($accepted) { "fixed_signal_planonly_on_clean_1h4h_slice" } else { "recollect_or_rescope_history" }
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    [ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = [string]$gateDoc.run_id
        status = [string]$gateDoc.status
        updated_at = [string]$gateDoc.updated_at
        manifest_path = [string]$gateDoc.manifest_path
        output = [ordered]@{ path = [string]$gateDoc.output_path; kind = "file" }
        collector_pid = $null
        monitor_pid = $null
        process_ids = @()
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $currentRunPath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 16
    exit 0
}

Write-Host "Slow-liquidity history data-quality" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Accepted: $($result.accepted)"
Write-Host "Reasons: $(@($result.reasons) -join ', ')"
Write-Host "Warnings: $(@($result.warnings) -join ', ')"
Write-Host "OK rows/bases/slots: $($result.metrics.ok_rows) / $($result.metrics.ok_bases) / $($result.metrics.ok_market_granularity_slots)"
Write-Host "2-venue bases / clean 1h4h 2-venue bases: $($result.metrics.two_exchange_bases) / $($result.metrics.two_exchange_full_coverage_1h4h_bases)"
Write-Host "Replay allowed: $($result.replay_allowed)"
Write-Host "Output: $OutputPath"
