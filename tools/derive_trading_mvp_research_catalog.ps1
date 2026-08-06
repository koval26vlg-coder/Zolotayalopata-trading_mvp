param(
    [string]$AuditPath = "",
    [string]$CatalogOutputPath = "",
    [string]$CatalogId = "",
    [switch]$Activate,
    [string]$PolicyPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\plans\trading-mvp-autopilot-policy-v1.json",
    [string]$BacklogPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\trading-mvp-autopilot-research-backlog.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "C:\Program Files\Python313\python.exe"
$module = Join-Path $repoRoot "trading_mvp\src\autopilot_catalog_deriver.py"
$researchRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
if (-not $AuditPath) {
    $latestAudit = Get-ChildItem -LiteralPath $researchRoot -File `
        -Filter "paper-product-readiness-audit-v*.json" |
        Sort-Object -Property LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $latestAudit) {
        throw "No immutable paper-product-readiness audit was found in $researchRoot."
    }
    $AuditPath = $latestAudit.FullName
}
if (-not (Test-Path -LiteralPath $AuditPath -PathType Leaf)) {
    throw "Readiness audit does not exist: $AuditPath"
}
$auditHash = (Get-FileHash -LiteralPath $AuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
$auditHashPrefix = $auditHash.Substring(0, 12)
if (-not $CatalogId) {
    $CatalogId = "trading_mvp_autopilot_research_catalog_$auditHashPrefix"
}
if (-not $CatalogOutputPath) {
    $CatalogOutputPath = Join-Path $repoRoot `
        "docs\plans\trading-mvp-autopilot-research-catalog-$auditHashPrefix.json"
}
$arguments = @(
    $module,
    "--audit", $AuditPath,
    "--catalog-output", $CatalogOutputPath,
    "--catalog-id", $CatalogId,
    "--reuse-existing"
)
if ($Activate) {
    $arguments += @(
        "--activate",
        "--policy", $PolicyPath,
        "--backlog", $BacklogPath
    )
}
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Catalog derivation failed with exit code $LASTEXITCODE."
}
