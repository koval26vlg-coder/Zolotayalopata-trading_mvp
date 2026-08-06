param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$ResultPath,
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 300)][int]$MaxRuntimeSec = 120,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60,
    [string]$ProjectRoot = "C:\Users\koval\Documents\ZolotyayLopata",
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [switch]$ConfirmedGateMomentumIdentityMetadataCollect
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmedGateMomentumIdentityMetadataCollect) {
    throw "Actual network collect requires -ConfirmedGateMomentumIdentityMetadataCollect."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Common = Join-Path $PSScriptRoot "visible_owned_metadata_collect_common.ps1"
$Module = Join-Path $RepoRoot "trading_mvp\src\gate_momentum_identity.py"
foreach ($required in @($Common, $Module)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required project file is missing: $required"
    }
}

. $Common
$invoke = @{
    PlanPath = $PlanPath
    ExpectedPlanHash = $ExpectedPlanHash
    ModulePath = $Module
    ResultPath = $ResultPath
    RunId = $RunId
    RunType = "gate_momentum_identity_metadata_collect"
    CredentialEnvironmentVariable = "TARDIS_API_KEY"
    ProjectRoot = $ProjectRoot
    MaxRuntimeSec = $MaxRuntimeSec
    HoldOpenSec = $HoldOpenSec
}
foreach ($optional in @{
    GatePath = $GatePath
    CurrentRunPath = $CurrentRunPath
    LaunchRecordPath = $LaunchRecordPath
    LogPath = $LogPath
}.GetEnumerator()) {
    if (-not [string]::IsNullOrWhiteSpace([string]$optional.Value)) {
        $invoke[$optional.Key] = $optional.Value
    }
}

$exitCode = Invoke-VisibleOwnedMetadataCollect @invoke
exit $exitCode
