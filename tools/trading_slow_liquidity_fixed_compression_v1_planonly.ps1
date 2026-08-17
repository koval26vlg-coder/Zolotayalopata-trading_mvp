param(
    [string]$HistoryJsonlPath = "",
    [string]$HistoryManifestPath = "",
    [string]$FixedSignalV0Path = "",
    [string]$QualityPath = "",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_fixed_compression_v1_plan.py"
$decision = "SLOW_LIQUIDITY_FIXED_V1_COMPRESSION_PLANONLY_READY_FOR_FEATURE_NORMALIZER"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_fixed_compression_v1_planonly_$timestamp.json"
}

function Resolve-RepoPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) { return "" }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
}

function Set-JsonProperty {
    param([Parameter(Mandatory = $true)]$Object, [Parameter(Mandatory = $true)][string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Save-Result {
    param($Payload)
    $outDir = Split-Path -Parent $OutputPath
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Json) { $Payload | ConvertTo-Json -Depth 24; return }
    Write-Host "Slow-liquidity fixed compression v1 PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Plan hash: $($Payload.plan_hash)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        mode = "slow_liquidity_fixed_compression_v1_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        research_only = $true
        strategy_accepted = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        gate_status = $gate.status
        reason = "Active run gate is $($gate.status); no new PlanOnly may be built over that run."
        output_path = $OutputPath
    }
    Save-Result -Payload $blocked
    exit 0
}

$gateDoc = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { $null }
if (-not $HistoryJsonlPath -and $gateDoc) { $HistoryJsonlPath = [string]$gateDoc.last_slow_liquidity_history_collect_output_path }
if (-not $HistoryManifestPath -and $gateDoc) { $HistoryManifestPath = [string]$gateDoc.last_slow_liquidity_history_collect_manifest_path }
if (-not $FixedSignalV0Path -and $gateDoc) { $FixedSignalV0Path = [string]$gateDoc.last_slow_liquidity_fixed_signal_plan_output_path }
if (-not $QualityPath -and $gateDoc) { $QualityPath = [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path }

$HistoryJsonlPath = Resolve-RepoPath $HistoryJsonlPath
$HistoryManifestPath = Resolve-RepoPath $HistoryManifestPath
$FixedSignalV0Path = Resolve-RepoPath $FixedSignalV0Path
$QualityPath = Resolve-RepoPath $QualityPath
$OutputPath = Resolve-RepoPath $OutputPath
foreach ($requiredPath in @($HistoryJsonlPath, $HistoryManifestPath, $FixedSignalV0Path, $QualityPath, $modulePath)) {
    if (-not $requiredPath -or -not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath"
    }
}

$pythonCandidates = @(
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $python = $pythonCommand.Source }
}
if (-not $python) { throw "Python runtime not found." }

$argsList = @(
    $modulePath,
    "--history-jsonl", $HistoryJsonlPath,
    "--history-manifest", $HistoryManifestPath,
    "--fixed-signal-v0", $FixedSignalV0Path,
    "--quality", $QualityPath,
    "--output", $OutputPath
)
$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) { throw "slow_liquidity_fixed_compression_v1_plan.py failed with exit code $LASTEXITCODE" }
$result = $raw | ConvertFrom-Json
$result | Add-Member -NotePropertyName "gate_status" -NotePropertyValue ([string]$gate.status) -Force

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $outputSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
    $nextStep = "Run the existing slow-liquidity feature normalizer once using this immutable v1 compression PlanOnly. No grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Fixed v1 compression PlanOnly is ready. The inherited threshold is frozen; only the dimensional normalization changed."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_compression_v1_plan_at" -Value ([string]$result.generated_at)
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_compression_v1_plan_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_compression_v1_plan_file_sha256" -Value $outputSha
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_compression_v1_plan_hash" -Value ([string]$result.plan_hash)
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = "fixed_compression_v1_planonly_ready_for_feature_normalizer"
        decision_source = $OutputPath
        plan_hash = [string]$result.plan_hash
        plan_file_sha256 = $outputSha
        selected_at = [string]$result.generated_at
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        v0_disposition = "REJECTED_AS_DEGENERATE"
        next_step_required = "run_slow_liquidity_feature_normalizer_on_fixed_compression_v1"
    })
    $gateDoc | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true -Force
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false -Force
}

Save-Result -Payload $result
