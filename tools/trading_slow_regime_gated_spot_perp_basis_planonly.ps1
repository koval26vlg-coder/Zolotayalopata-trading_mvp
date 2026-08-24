param(
    [string]$OutputPath = "",
    [string]$ProbePath = "",
    [string]$IdentityPath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$modulePath = Join-Path $repoRoot "trading_mvp\src\slow_regime_gated_spot_perp_basis.py"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_regime_gated_spot_perp_basis_planonly_$timestamp.json"
}

function Save-Result {
    param($Payload)
    $outDir = Split-Path -Parent $OutputPath
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 20
        return
    }
    Write-Host "Slow-regime-gated spot/perp basis PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $OutputPath"
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

$gateRaw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json
if ($LASTEXITCODE -ne 0) {
    throw "check_active_run_gate failed with exit code $LASTEXITCODE"
}
$gate = $gateRaw | ConvertFrom-Json

if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "slow_regime_gated_spot_perp_basis_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "slow_regime_gated_spot_perp_basis_v1"
        would_start = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        gate_status = $gate.status
        reason = "Active run gate is $($gate.status); combo PlanOnly waits for gate resolution."
        output_path = $OutputPath
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$python = Resolve-Python
$argsList = @($modulePath, "--repo-root", $repoRoot, "--out", $OutputPath)
if ($ProbePath) { $argsList += @("--probe-path", $ProbePath) }
if ($IdentityPath) { $argsList += @("--identity-path", $IdentityPath) }
& $python @argsList | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "slow_regime_gated_spot_perp_basis.py failed with exit code $LASTEXITCODE"
}

$result = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
$result | Add-Member -NotePropertyName gate_status -NotePropertyValue $gate.status -Force
$result | Add-Member -NotePropertyName gate_updated -NotePropertyValue $false -Force
$result | Add-Member -NotePropertyName commands -NotePropertyValue ([ordered]@{
    rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
    active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
}) -Force
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 20
} else {
    Write-Host "Slow-regime-gated spot/perp basis PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($result.decision)"
    Write-Host "Plan hash: $($result.plan_hash)"
    Write-Host "Intersection: $($result.feasibility.intersection_count)"
    Write-Host "Output: $OutputPath"
}
