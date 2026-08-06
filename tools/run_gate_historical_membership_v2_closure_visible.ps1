param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ProbePath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 300,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Module = Join-Path $RepoRoot 'trading_mvp\src\gate_historical_membership_v2_closure.py'
$LogDirectory = Join-Path $RepoRoot 'exports\trading-mvp\run'
$LogPath = Join-Path $LogDirectory "$RunId.closure.visible.log"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$candidates = @(
    $env:TRADING_MVP_PYTHON,
    (Join-Path $RepoRoot '.venv\Scripts\python.exe'),
    (Join-Path $RepoRoot 'trading_mvp\.venv\Scripts\python.exe'),
    'C:\Program Files\Python313\python.exe',
    'C:\Program Files\Python312\python.exe',
    'C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
) | Where-Object { $_ }
$Python = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $Python = [System.IO.Path]::GetFullPath($candidate)
        break
    }
}
if (-not $Python) {
    throw 'Python runtime was not found. Set TRADING_MVP_PYTHON.'
}
if (-not (Test-Path -LiteralPath $Module -PathType Leaf)) {
    throw "Closure module is missing: $Module"
}

$arguments = @(
    '-u', $Module, 'build',
    '--plan', ([System.IO.Path]::GetFullPath($PlanPath)),
    '--probe', ([System.IO.Path]::GetFullPath($ProbePath)),
    '--output-dir', ([System.IO.Path]::GetFullPath($OutputDirectory)),
    '--run-id', $RunId,
    '--max-runtime-sec', [string]$MaxRuntimeSec
)

"[$(Get-Date -Format o)] visible membership-v2 closure start run_id=$RunId" |
    Tee-Object -FilePath $LogPath
& $Python @arguments 2>&1 | Tee-Object -FilePath $LogPath -Append
$exitCode = $LASTEXITCODE
"[$(Get-Date -Format o)] visible membership-v2 closure exit_code=$exitCode" |
    Tee-Object -FilePath $LogPath -Append
if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit $exitCode
