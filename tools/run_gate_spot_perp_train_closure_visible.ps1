param(
    [Parameter(Mandatory = $true)][string]$ParentPlan,
    [Parameter(Mandatory = $true)][string]$ExpectedParentPlanHash,
    [Parameter(Mandatory = $true)][string]$CollectorManifest,
    [Parameter(Mandatory = $true)][string]$QualityReport,
    [Parameter(Mandatory = $true)][string]$TrainPlan,
    [Parameter(Mandatory = $true)][string]$ExpectedTrainPlanHash,
    [Parameter(Mandatory = $true)][string]$TrainResult,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = 'C:\Program Files\Python313\python.exe'
$Module = Join-Path $RepoRoot 'trading_mvp\src\spot_perp_basis_history_v2_report.py'
$LogDirectory = Join-Path $RepoRoot 'exports\trading-mvp\run'
$LogPath = Join-Path $LogDirectory "$RunId.closure.visible.log"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$arguments = @(
    '-u', $Module,
    '--parent-plan', $ParentPlan,
    '--expected-parent-plan-hash', $ExpectedParentPlanHash,
    '--collector-manifest', $CollectorManifest,
    '--quality-report', $QualityReport,
    '--train-plan', $TrainPlan,
    '--expected-train-plan-hash', $ExpectedTrainPlanHash,
    '--train-result', $TrainResult,
    '--output-directory', $OutputDirectory,
    '--run-id', $RunId,
    '--max-runtime-sec', [string]$MaxRuntimeSec
)

"[$(Get-Date -Format o)] visible closure start run_id=$RunId" | Tee-Object -FilePath $LogPath
& $Python @arguments 2>&1 | Tee-Object -FilePath $LogPath -Append
$exitCode = $LASTEXITCODE
"[$(Get-Date -Format o)] visible closure exit_code=$exitCode" | Tee-Object -FilePath $LogPath -Append
if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit $exitCode
