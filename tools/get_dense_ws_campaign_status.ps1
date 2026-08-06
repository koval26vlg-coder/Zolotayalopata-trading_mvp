param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedPlanHash,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $projectRoot "trading_mvp\src\dense_ws_campaign_runner.py"
$python = if (
    $env:TRADING_MVP_PYTHON -and
    (Test-Path -LiteralPath $env:TRADING_MVP_PYTHON -PathType Leaf)
) {
    $env:TRADING_MVP_PYTHON
} else {
    "C:\Program Files\Python313\python.exe"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Campaign Python runtime is missing: $python"
}
$raw = & $python $runner status `
    --plan ([System.IO.Path]::GetFullPath($PlanPath)) `
    --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) {
    throw "Campaign status failed."
}
$payload = (($raw | Out-String) | ConvertFrom-Json)
if ($Json) {
    $payload | ConvertTo-Json -Depth 30
} else {
    $payload | Format-List
}
