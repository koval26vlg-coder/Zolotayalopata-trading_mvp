[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PatchPath,

    [Parameter(Mandatory)]
    [string]$SourcePath,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Fa-f0-9]{64}$')]
    [string]$ExpectedSourceSha256,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Fa-f0-9]{64}$')]
    [string]$ExpectedPostimageSha256,

    [string]$GitPath
)

$ErrorActionPreference = 'Stop'

function Get-Sha256 {
    param([Parameter(Mandatory)][string]$LiteralPath)

    return (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Get-PatchTargetPath {
    param([Parameter(Mandatory)][string]$LiteralPath)

    $oldHeaders = @()
    $newHeaders = @()
    foreach ($line in [System.IO.File]::ReadAllLines($LiteralPath)) {
        if ($line.StartsWith('--- ')) {
            $oldHeaders += $line.Substring(4).Split("`t", 2)[0]
        }
        elseif ($line.StartsWith('+++ ')) {
            $newHeaders += $line.Substring(4).Split("`t", 2)[0]
        }
    }

    if ($oldHeaders.Count -ne 1 -or $newHeaders.Count -ne 1) {
        throw 'patch must contain exactly one old and one new file header'
    }

    $oldPath = [string]$oldHeaders[0]
    $newPath = [string]$newHeaders[0]
    if ($oldPath -eq '/dev/null' -or $newPath -eq '/dev/null') {
        throw 'create/delete patches are not allowed'
    }
    if (-not $oldPath.StartsWith('a/') -or -not $newPath.StartsWith('b/')) {
        throw 'patch paths must use a/ and b/ prefixes'
    }

    $oldRelative = $oldPath.Substring(2).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    $newRelative = $newPath.Substring(2).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    if ($oldRelative -ne $newRelative) {
        throw 'rename patches are not allowed'
    }
    if ([System.IO.Path]::IsPathRooted($newRelative) -or $newRelative.Split([System.IO.Path]::DirectorySeparatorChar) -contains '..') {
        throw 'patch target path must stay inside the isolated temporary directory'
    }

    return $newRelative
}

function Resolve-GitPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        $resolved = (Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop).Path
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "git executable is not a file: $resolved"
        }
        return $resolved
    }

    $bundledGit = Join-Path ${env:ProgramFiles} 'Git\cmd\git.exe'
    if (Test-Path -LiteralPath $bundledGit -PathType Leaf) {
        return $bundledGit
    }

    $git = Get-Command git -ErrorAction Stop
    return $git.Source
}

function Write-Result {
    param(
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$PatchPath,
        [Parameter(Mandatory)][string]$ExpectedSourceSha256,
        [Parameter(Mandatory)][string]$ObservedSourceSha256,
        [Parameter(Mandatory)][string]$ExpectedPostimageSha256,
        [string]$ObservedPostimageSha256,
        [string]$PatchTargetPath
    )

    [pscustomobject]@{
        schema = 'trading_mvp_patch_postimage_verification_v1'
        status = $Status
        source_path = $SourcePath
        patch_path = $PatchPath
        patch_target_path = $PatchTargetPath
        expected_source_sha256 = $ExpectedSourceSha256
        observed_source_sha256 = $ObservedSourceSha256
        expected_postimage_sha256 = $ExpectedPostimageSha256
        observed_postimage_sha256 = $ObservedPostimageSha256
        isolated_apply = $true
        source_file_written = $false
        network_access = $false
    } | ConvertTo-Json -Depth 4 -Compress
}

$source = (Resolve-Path -LiteralPath $SourcePath -ErrorAction Stop).Path
$patch = (Resolve-Path -LiteralPath $PatchPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "source path is not a file: $source"
}
if (-not (Test-Path -LiteralPath $patch -PathType Leaf)) {
    throw "patch path is not a file: $patch"
}

$expectedSource = $ExpectedSourceSha256.ToLowerInvariant()
$expectedPostimage = $ExpectedPostimageSha256.ToLowerInvariant()
$observedSource = Get-Sha256 -LiteralPath $source
if ($observedSource -ne $expectedSource) {
    Write-Result -Status 'FAIL_SOURCE_PREIMAGE' -SourcePath $source -PatchPath $patch -ExpectedSourceSha256 $expectedSource -ObservedSourceSha256 $observedSource -ExpectedPostimageSha256 $expectedPostimage
    exit 2
}

$targetRelative = Get-PatchTargetPath -LiteralPath $patch
$git = Resolve-GitPath -RequestedPath $GitPath
$temporaryBase = [System.IO.Path]::GetTempPath()
$temporaryRoot = Join-Path $temporaryBase ('trading-mvp-patch-postimage-' + [guid]::NewGuid().ToString('N'))
$temporaryTarget = Join-Path $temporaryRoot $targetRelative

try {
    New-Item -ItemType Directory -Path (Split-Path -Parent $temporaryTarget) -Force | Out-Null
    [System.IO.File]::Copy($source, $temporaryTarget, $true)

    $checkOutput = & $git -C $temporaryRoot apply --check --whitespace=nowarn -- $patch 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "git apply --check failed: $checkOutput"
    }
    $applyOutput = & $git -C $temporaryRoot apply --whitespace=nowarn -- $patch 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "git apply failed: $applyOutput"
    }

    $observedPostimage = Get-Sha256 -LiteralPath $temporaryTarget
    $status = if ($observedPostimage -eq $expectedPostimage) { 'PASS' } else { 'FAIL_POSTIMAGE' }
    Write-Result -Status $status -SourcePath $source -PatchPath $patch -ExpectedSourceSha256 $expectedSource -ObservedSourceSha256 $observedSource -ExpectedPostimageSha256 $expectedPostimage -ObservedPostimageSha256 $observedPostimage -PatchTargetPath $targetRelative
    if ($status -ne 'PASS') {
        exit 3
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $fullTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
        $fullTemporaryBase = [System.IO.Path]::GetFullPath($temporaryBase)
        if (-not $fullTemporaryRoot.StartsWith($fullTemporaryBase, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to remove a path outside the temporary directory: $fullTemporaryRoot"
        }
        Remove-Item -LiteralPath $fullTemporaryRoot -Recurse -Force
    }
}
