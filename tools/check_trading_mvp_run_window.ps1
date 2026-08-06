param(
    [string]$PolicyPath = "",
    [string]$ObservedAtUtc = "",
    [string]$RequestedStartLocal = "",
    [int]$ExpectedDurationSec = 0,
    [int]$MaxRuntimeSec = 0,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $PolicyPath) {
    $PolicyPath = Join-Path $repoRoot "docs\plans\trading-mvp-continuous-production-policy-v1.json"
}
$evaluator = Join-Path $repoRoot "trading_mvp\src\continuous_production.py"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    $resolved = $candidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ($resolved) {
        return $resolved
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

if (-not (Test-Path -LiteralPath $PolicyPath)) {
    throw "Continuous production policy not found: $PolicyPath"
}
if (-not (Test-Path -LiteralPath $evaluator)) {
    throw "Continuous production evaluator not found: $evaluator"
}

$python = Resolve-Python
$arguments = @($evaluator, "--policy", $PolicyPath)
if ($RequestedStartLocal) {
    if ($ExpectedDurationSec -le 0 -or $MaxRuntimeSec -le 0) {
        throw "RequestedStartLocal requires positive ExpectedDurationSec and MaxRuntimeSec."
    }
    $arguments += @(
        "--requested-start-local", $RequestedStartLocal,
        "--expected-duration-sec", [string]$ExpectedDurationSec,
        "--max-runtime-sec", [string]$MaxRuntimeSec
    )
} elseif ($ObservedAtUtc) {
    $arguments += @("--observed-at-utc", $ObservedAtUtc)
}

$output = & $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Run-window evaluator failed with exit code $LASTEXITCODE."
}
$result = ($output | Out-String).Trim() | ConvertFrom-Json
if ($Json) {
    $result | ConvertTo-Json -Depth 12
    exit 0
}

Write-Host "trading_mvp rolling run window" -ForegroundColor Cyan
Write-Host "Status: $($result.status)"
Write-Host "Window: $($result.window_type)"
Write-Host "Observed: $($result.observed_at_local)"
Write-Host "Hard deadline: $($result.hard_deadline_local)"
Write-Host "Maximum remaining runtime: $($result.max_remaining_runtime_sec) sec"
Write-Host "Approval request: $($result.approval_request_status)"
