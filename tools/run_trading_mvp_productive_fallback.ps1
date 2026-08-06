param(
    [string]$PolicyPath = "",
    [string]$TaskId = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$guardWrapper = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$runner = Join-Path $repoRoot "trading_mvp\src\autopilot_work_queue.py"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    $resolved = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($resolved) { return $resolved }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

if (-not $PolicyPath) {
    $PolicyPath = Join-Path $repoRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
}
foreach ($required in @($guardWrapper, $runner, $PolicyPath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required productive fallback input is missing: $required"
    }
}

$guardJson = & pwsh -NoProfile -ExecutionPolicy Bypass -File $guardWrapper `
    -PolicyPath $PolicyPath -Json
if ($LASTEXITCODE -ne 0) {
    throw "Autopilot guard failed with exit code $LASTEXITCODE."
}
$guard = (@($guardJson) -join [Environment]::NewLine) | ConvertFrom-Json
if ($guard.decision -ne "CONTINUE_PRODUCTIVE_FALLBACK") {
    [pscustomobject]@{
        status = "SKIPPED"
        reason = $guard.decision
        next_action = $guard.next_action
        weekly_remaining_percent = $guard.usage.remaining_percent
    } | ConvertTo-Json -Depth 8
    exit 0
}

$selectedTask = if ($TaskId) { $TaskId } else { [string]$guard.next_action }
if (-not $selectedTask) {
    throw "Autopilot selected an empty fallback task id."
}

$python = Resolve-Python
Write-Host "[fallback] task=$selectedTask weekly_remaining=$($guard.usage.remaining_percent)%" -ForegroundColor Cyan
& $python $runner `
    --policy $PolicyPath `
    --repo-root $repoRoot `
    --task-id $selectedTask
if ($LASTEXITCODE -ne 0) {
    throw "Productive fallback task failed with exit code $LASTEXITCODE."
}
