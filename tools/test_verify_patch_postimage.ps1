[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Get-Sha256 {
    param([Parameter(Mandatory)][string]$LiteralPath)

    return (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Assert-Equal {
    param(
        [Parameter(Mandatory)]$Actual,
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)][string]$Label
    )

    if ($Actual -ne $Expected) {
        throw "$Label expected '$Expected', got '$Actual'"
    }
}

$root = Split-Path -Parent $PSScriptRoot
$verifier = Join-Path $PSScriptRoot 'verify_patch_postimage.ps1'
$git = Join-Path ${env:ProgramFiles} 'Git\cmd\git.exe'
$v2Patch = Join-Path $root 'docs\plans\drafts\dense-ws-aef-time-only-reschedule-refreeze-implementation-preview-20260803-v2.patch'
$v2Source = Join-Path $root 'trading_mvp\src\dense_ws_campaign_contract.py'
if (-not (Test-Path -LiteralPath $git -PathType Leaf)) {
    throw "bundled git executable is missing: $git"
}

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('trading-mvp-patch-postimage-test-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    $fixture = Join-Path $temporaryRoot 'fixture.txt'
    $fixturePatch = Join-Path $temporaryRoot 'fixture.patch'
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $crlf = [Environment]::NewLine
    [System.IO.File]::WriteAllText($fixture, "before$crlf" + "after$crlf", $utf8)
    [System.IO.File]::WriteAllText($fixturePatch, "--- a/fixture.txt`n+++ b/fixture.txt`n@@ -1,2 +1,2 @@`n-before`n+changed`n after`n", $utf8)
    $expectedFixturePostimage = Join-Path $temporaryRoot 'fixture-postimage.txt'
    [System.IO.File]::WriteAllText($expectedFixturePostimage, "changed$crlf" + "after$crlf", $utf8)

    $fixtureResult = & $verifier -PatchPath $fixturePatch -SourcePath $fixture -ExpectedSourceSha256 (Get-Sha256 $fixture) -ExpectedPostimageSha256 (Get-Sha256 $expectedFixturePostimage) -GitPath $git
    Assert-Equal -Actual $LASTEXITCODE -Expected 0 -Label 'fixture verifier exit code'
    Assert-Equal -Actual (($fixtureResult -join "`n") | ConvertFrom-Json).status -Expected 'PASS' -Label 'fixture verifier status'

    $wrongHashResult = & $verifier -PatchPath $fixturePatch -SourcePath $fixture -ExpectedSourceSha256 (Get-Sha256 $fixture) -ExpectedPostimageSha256 ('0' * 64) -GitPath $git
    Assert-Equal -Actual $LASTEXITCODE -Expected 3 -Label 'wrong postimage exit code'
    Assert-Equal -Actual (($wrongHashResult -join "`n") | ConvertFrom-Json).status -Expected 'FAIL_POSTIMAGE' -Label 'wrong postimage status'

    $v2Root = Join-Path $temporaryRoot 'v2'
    $v2Target = Join-Path $v2Root 'trading_mvp\src\dense_ws_campaign_contract.py'
    New-Item -ItemType Directory -Path (Split-Path -Parent $v2Target) -Force | Out-Null
    [System.IO.File]::Copy($v2Source, $v2Target, $true)
    & $git -C $v2Root apply --check --reverse --whitespace=nowarn -- $v2Patch
    Assert-Equal -Actual $LASTEXITCODE -Expected 0 -Label 'v2 reverse check exit code'
    & $git -C $v2Root apply --reverse --whitespace=nowarn -- $v2Patch
    Assert-Equal -Actual $LASTEXITCODE -Expected 0 -Label 'v2 reverse apply exit code'

    $derivedPreimage = Get-Sha256 $v2Target
    $observedV2Postimage = Get-Sha256 $v2Source
    $v2PassResult = & $verifier -PatchPath $v2Patch -SourcePath $v2Target -ExpectedSourceSha256 $derivedPreimage -ExpectedPostimageSha256 $observedV2Postimage -GitPath $git
    Assert-Equal -Actual $LASTEXITCODE -Expected 0 -Label 'v2 observed postimage exit code'
    Assert-Equal -Actual (($v2PassResult -join "`n") | ConvertFrom-Json).status -Expected 'PASS' -Label 'v2 observed postimage status'

    $legacyClaimResult = & $verifier -PatchPath $v2Patch -SourcePath $v2Target -ExpectedSourceSha256 $derivedPreimage -ExpectedPostimageSha256 '9aac8ceac80acff9971b3bf72acdcabfd3560d2f42fd5e8a14912d659c150aac' -GitPath $git
    Assert-Equal -Actual $LASTEXITCODE -Expected 3 -Label 'legacy claim exit code'
    Assert-Equal -Actual (($legacyClaimResult -join "`n") | ConvertFrom-Json).status -Expected 'FAIL_POSTIMAGE' -Label 'legacy claim status'

    [pscustomobject]@{
        schema = 'trading_mvp_patch_postimage_verifier_test_v1'
        status = 'PASS'
        fixture_passed = $true
        wrong_expected_postimage_rejected = $true
        legacy_v2_claim_rejected = $true
        v2_derived_preimage_sha256 = $derivedPreimage
        v2_observed_postimage_sha256 = $observedV2Postimage
        network_access = $false
        source_or_contract_mutated = $false
    } | ConvertTo-Json -Depth 4 -Compress
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $fullTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
        $fullTemporaryBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (-not $fullTemporaryRoot.StartsWith($fullTemporaryBase, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to remove a path outside the temporary directory: $fullTemporaryRoot"
        }
        Remove-Item -LiteralPath $fullTemporaryRoot -Recurse -Force
    }
}
