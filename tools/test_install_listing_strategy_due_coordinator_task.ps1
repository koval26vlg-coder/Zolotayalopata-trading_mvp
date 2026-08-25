$ErrorActionPreference = "Stop"

$installerPath = Join-Path $PSScriptRoot "install_listing_strategy_due_coordinator_task.ps1"
$pwsh = (Get-Process -Id $PID).Path

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$source = Get-Content -Raw -LiteralPath $installerPath
Assert-True ($source -match 'ExpectedReceiptSha256') "installer does not bind receipt SHA"
Assert-True ($source -match 'ExpectedInstallerSha256') "installer does not bind its own SHA"
Assert-True ($source -match 'ExpectedValidatorSha256') "installer does not bind validator SHA"
Assert-True ($source -match 'ExpectedControlPlaneGitCommit') "installer does not bind control-plane commit"
Assert-True ($source -match 'GetFinalPathNameByHandle') "installer does not resolve physical paths"
Assert-True ($source -match 'materialization_receipt\.v2') "installer does not require the materialization receipt"
Assert-True ($source -match 'canonical_strategy_runtime\.json') "installer does not require the canonical registry filename"
Assert-True ($source -match 'materialization_receipt\.json') "installer does not require the canonical receipt filename"
Assert-True ($source -match 'Assert-ControlPlaneBinding') "installer does not recheck the committed trust root"
Assert-True ($source -match 'Assert-PublicationBinding') "installer does not recheck the publication pair"
Assert-True ($source -notmatch '\[string\]\$CoordinatorPath') "production installer accepts a coordinator override"

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("listing-installer-path-override-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $fakeCoordinator = Join-Path $tempRoot "fake-coordinator.ps1"
    $marker = Join-Path $tempRoot "executed.marker"
    "[IO.File]::WriteAllText('$($marker.Replace("'", "''"))','executed')" | Set-Content -LiteralPath $fakeCoordinator -Encoding utf8NoBOM
    $arguments = @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $installerPath,
        "-DryRun", "-Json",
        "-RegistryPath", (Join-Path $tempRoot "missing-registry.json"),
        "-ReceiptPath", (Join-Path $tempRoot "missing-receipt.json"),
        "-ExpectedRegistrySha256", ("0" * 64),
        "-ExpectedReceiptSha256", ("0" * 64),
        "-ExpectedInstallerSha256", ("0" * 64),
        "-ExpectedCoordinatorSha256", ("0" * 64),
        "-ExpectedValidatorSha256", ("0" * 64),
        "-ExpectedControlPlaneGitCommit", ("0" * 40),
        "-CoordinatorPath", $fakeCoordinator
    )
    $output = & $pwsh @arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    Assert-True ($exitCode -ne 0) "arbitrary CoordinatorPath override was accepted"
    Assert-True (-not (Test-Path -LiteralPath $marker)) "arbitrary coordinator was executed"
    Assert-True ($output -match 'CoordinatorPath') "parameter-binding rejection did not identify CoordinatorPath"

    [ordered]@{
        status = "PASS"
        tests = 12
        registration_attempted = $false
        arbitrary_coordinator_executed = $false
    } | ConvertTo-Json -Compress
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $resolved = (Resolve-Path -LiteralPath $tempRoot).Path
        $tempBase = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to remove temp path outside system temp: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
