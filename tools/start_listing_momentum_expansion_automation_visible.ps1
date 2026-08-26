param(
    [string]$PlanPath = "",
    [switch]$Status,
    [switch]$Reconcile,
    [switch]$DryRun,
    [switch]$Tick,
    [switch]$Json
)

# Visible launcher for the listing-expansion automation wrapper.
#
# This is deliberately thin. The wrapper that preceded it carried eleven hundred lines
# of PowerShell that reimplemented scheduler state, claim ownership, process liveness
# and the cadence ladder - all of which now live in tested Python modules bound by the
# wrapper's PlanOnly file. Re-expressing any of that here would give the automation two
# implementations of the same rules and no way to tell which one was in force.
#
# So this script does three things and nothing else: it refuses to run outside its own
# repository, it resolves an interpreter by absolute path rather than by search order,
# and it runs the wrapper in this window so the tick is genuinely visible.

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $repoRoot "trading_mvp\src\listing_expansion_automation.py"
$defaultPlanPath = Join-Path $repoRoot "docs\plans\listing-momentum-expansion-automation-planonly-20260826-v2.json"
if (-not $PlanPath) { $PlanPath = $defaultPlanPath }

if (-not (Test-Path -LiteralPath $runner)) {
    throw "expansion automation runner not found: $runner"
}
if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "expansion automation plan not found: $PlanPath"
}

function Resolve-PythonExecutable {
    # An interpreter taken from PATH is chosen by whatever happens to be earliest on it,
    # which is not a decision this automation should delegate (CWE-426). PYTHON_EXE is
    # honoured because the scheduler sets it deliberately; everything else is an
    # absolute, known location.
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) { return $env:PYTHON_EXE }
    foreach ($candidate in @(
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\AppData\Local\Programs\Python\Python313\python.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Python executable not found; set PYTHON_EXE to an absolute path"
}

$selected = @($Status, $Reconcile, $DryRun, $Tick) | Where-Object { $_ }
if ($selected.Count -ne 1) {
    throw "choose exactly one of -Status, -Reconcile, -DryRun, -Tick"
}

$action = if ($Status) { "--status" }
    elseif ($Reconcile) { "--reconcile" }
    elseif ($DryRun) { "--dry-run" }
    else { "--tick" }

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$pythonExe = Resolve-PythonExecutable

if (-not $Json) {
    Write-Host "=== Listing expansion automation (visible) ===" -ForegroundColor Cyan
    Write-Host ("plan:   " + $PlanPath)
    Write-Host ("action: " + $action)
    Write-Host ""
}

Push-Location $repoRoot
try {
    & $pythonExe $runner --plan $PlanPath $action
    $exitCode = [int]$LASTEXITCODE
} finally {
    Pop-Location
}

if (-not $Json) {
    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "wrapper exited 0" -ForegroundColor Green
    } else {
        # A non-zero exit here means the wake was refused or left open on purpose.
        # It is not the same as a failed tick, and it must not be retried by hand
        # without reading the reason the wrapper printed.
        Write-Host ("wrapper exited " + $exitCode) -ForegroundColor Yellow
    }
}

exit $exitCode
