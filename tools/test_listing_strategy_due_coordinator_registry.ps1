param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$coordinatorPath = Join-Path $PSScriptRoot "invoke_listing_strategy_due_coordinator.ps1"
$stagingRegistryPath = Join-Path $repoRoot "docs\control\canonical_strategy_runtime.staging.json"
$pwshExe = (Get-Process -Id $PID).Path
$script:passed = 0
$script:failed = 0
$testRoot = Join-Path $PSScriptRoot (".test_listing_strategy_due_coordinator_registry_" + [guid]::NewGuid().ToString("N"))

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    if ($Actual -ne $Expected) {
        throw "$Message (expected=$Expected actual=$Actual)"
    }
}

function Invoke-Test {
    param([string]$Name, [scriptblock]$Body)
    try {
        & $Body
        $script:passed += 1
        Write-Host "PASS $Name" -ForegroundColor Green
    } catch {
        $script:failed += 1
        Write-Host "FAIL $Name :: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Get-RawSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-CoordinatorPreflight {
    param(
        [string]$RegistryPath,
        [string]$ExpectedRegistrySha256,
        [string]$ExpectedCoordinatorSha256,
        [string[]]$ExtraArguments = @(),
        [hashtable]$EnvironmentOverrides = @{}
    )
    $arguments = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $coordinatorPath,
        "-ScheduledTick",
        "-Json",
        "-RegistryPath", $RegistryPath,
        "-ExpectedRegistrySha256", $ExpectedRegistrySha256,
        "-ExpectedCoordinatorSha256", $ExpectedCoordinatorSha256
    )) {
        $arguments.Add($item)
    }
    foreach ($item in $ExtraArguments) { $arguments.Add($item) }

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pwshExe
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($entry in $EnvironmentOverrides.GetEnumerator()) {
        $startInfo.Environment[[string]$entry.Key] = [string]$entry.Value
    }
    foreach ($item in $arguments) { [void]$startInfo.ArgumentList.Add($item) }
    $process = [Diagnostics.Process]::Start($startInfo)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $payload = $null
    if ($stdout.Trim()) {
        try { $payload = $stdout | ConvertFrom-Json -DateKind String -ErrorAction Stop } catch { }
    }
    return [pscustomobject]@{
        exit_code = $process.ExitCode
        stdout = $stdout
        stderr = $stderr
        payload = $payload
    }
}

New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    $dummyRegistry = Join-Path $testRoot "dummy-registry.json"
    [IO.File]::WriteAllText($dummyRegistry, "{}`n", [Text.UTF8Encoding]::new($false))
    $dummyRegistrySha = Get-RawSha256 $dummyRegistry
    $coordinatorSha = Get-RawSha256 $coordinatorPath

    Invoke-Test "coordinator rejects a mismatched self hash before registry parsing" {
        $result = Invoke-CoordinatorPreflight `
            -RegistryPath $dummyRegistry `
            -ExpectedRegistrySha256 $dummyRegistrySha `
            -ExpectedCoordinatorSha256 ("0" * 64)
        Assert-Equal $result.exit_code 2 "self-hash mismatch must be nonzero: $($result.stderr)"
        Assert-True ($null -ne $result.payload) "self-hash mismatch did not return JSON: $($result.stdout) $($result.stderr)"
        Assert-Equal $result.payload.status "COORDINATOR_BINDING_INVALID" "wrong status for self-hash mismatch"
        Assert-Equal $result.payload.reason "COORDINATOR_SHA256_MISMATCH" "wrong self-hash mismatch reason"
        Assert-Equal $result.payload.execution_performed $false "self-hash mismatch performed execution"
    }

    Invoke-Test "coordinator rejects a mismatched raw registry hash before validation" {
        $result = Invoke-CoordinatorPreflight `
            -RegistryPath $dummyRegistry `
            -ExpectedRegistrySha256 ("f" * 64) `
            -ExpectedCoordinatorSha256 $coordinatorSha
        Assert-Equal $result.exit_code 2 "registry-hash mismatch must be nonzero: $($result.stderr)"
        Assert-True ($null -ne $result.payload) "registry-hash mismatch did not return JSON"
        Assert-Equal $result.payload.status "REGISTRY_BINDING_INVALID" "wrong status for registry-hash mismatch"
        Assert-Equal $result.payload.reason "REGISTRY_SHA256_MISMATCH" "wrong registry-hash mismatch reason"
        Assert-Equal $result.payload.execution_performed $false "registry-hash mismatch performed execution"
    }

    Invoke-Test "production launcher and state overrides fail closed" {
        $marker = Join-Path $testRoot "launcher-called.txt"
        $launcher = Join-Path $testRoot "forbidden-launcher.ps1"
        "[IO.File]::WriteAllText('$($marker.Replace("'", "''"))','called')" |
            Set-Content -LiteralPath $launcher -Encoding utf8NoBOM
        $result = Invoke-CoordinatorPreflight `
            -RegistryPath $dummyRegistry `
            -ExpectedRegistrySha256 $dummyRegistrySha `
            -ExpectedCoordinatorSha256 $coordinatorSha `
            -ExtraArguments @("-ListingLauncherPath", $launcher)
        Assert-Equal $result.exit_code 2 "path override must be nonzero: $($result.stderr)"
        Assert-True ($null -ne $result.payload) "path override did not return JSON"
        Assert-Equal $result.payload.status "PRODUCTION_OVERRIDE_REJECTED" "wrong path-override status"
        Assert-Equal $result.payload.reason "PRODUCTION_PATH_OVERRIDE_FORBIDDEN" "wrong path-override reason"
        Assert-True (-not (Test-Path -LiteralPath $marker)) "forbidden launcher was executed"
    }

    Invoke-Test "valid staging registry returns STAGED_FAIL_CLOSED without durable mutation" {
        Assert-True (Test-Path -LiteralPath $stagingRegistryPath -PathType Leaf) "staging registry is missing"
        $registrySha = Get-RawSha256 $stagingRegistryPath
        $protectedPaths = @(
            (Join-Path $repoRoot "docs\agent-log\run-gates\listing_strategy_due_coordinator_state.json"),
            (Join-Path $repoRoot "docs\agent-log\run-gates\listing_strategy_due_coordinator_attempts.jsonl"),
            (Join-Path $repoRoot "docs\agent-log\run-gates\listing_strategy_due_coordinator.claim.json")
        )
        $before = @{}
        foreach ($path in $protectedPaths) {
            $before[$path] = if (Test-Path -LiteralPath $path -PathType Leaf) { Get-RawSha256 $path } else { $null }
        }
        $result = Invoke-CoordinatorPreflight `
            -RegistryPath $stagingRegistryPath `
            -ExpectedRegistrySha256 $registrySha `
            -ExpectedCoordinatorSha256 $coordinatorSha
        Assert-Equal $result.exit_code 0 "valid staging registry must be an acknowledged no-op: $($result.stdout) $($result.stderr)"
        Assert-True ($null -ne $result.payload) "staging result did not return JSON"
        Assert-Equal $result.payload.status "STAGED_FAIL_CLOSED" "staging registry was not blocked"
        Assert-Equal $result.payload.reason "NOT_ACTIVATED" "staging reason is not explicit"
        Assert-Equal $result.payload.execution_performed $false "staging registry executed work"
        Assert-Equal $result.payload.launch_allowed $false "staging registry allowed launch"
        Assert-Equal $result.payload.registry_raw_sha256 $registrySha "staging output lost registry binding"
        foreach ($path in $protectedPaths) {
            $after = if (Test-Path -LiteralPath $path -PathType Leaf) { Get-RawSha256 $path } else { $null }
            Assert-Equal $after $before[$path] "staging preflight mutated $path"
        }
    }

    Invoke-Test "coordinator does not trust a PATH-shadowed Python command" {
        Assert-True (Test-Path -LiteralPath $stagingRegistryPath -PathType Leaf) "staging registry is missing"
        $shadowDir = Join-Path $testRoot "shadow-bin"
        New-Item -ItemType Directory -Path $shadowDir | Out-Null
        $shadowMarker = Join-Path $testRoot "shadow-python-called.txt"
        $shadowPython = Join-Path $shadowDir "python.cmd"
        @"
@echo off
echo called>"$shadowMarker"
echo {"ok":true,"registry_valid":true,"decision":"STAGED_FAIL_CLOSED","launch_allowed":false,"reasons":[],"runtimes":[]}
exit /b 0
"@ | Set-Content -LiteralPath $shadowPython -Encoding ascii
        $registrySha = Get-RawSha256 $stagingRegistryPath
        $shadowPath = "$shadowDir;$([Environment]::GetEnvironmentVariable('PATH'))"
        $result = Invoke-CoordinatorPreflight `
            -RegistryPath $stagingRegistryPath `
            -ExpectedRegistrySha256 $registrySha `
            -ExpectedCoordinatorSha256 $coordinatorSha `
            -EnvironmentOverrides @{ PATH = $shadowPath }
        Assert-Equal $result.exit_code 0 "PATH shadow changed registry validation: $($result.stdout) $($result.stderr)"
        Assert-Equal $result.payload.status "STAGED_FAIL_CLOSED" "PATH shadow changed coordinator decision"
        Assert-True (-not (Test-Path -LiteralPath $shadowMarker)) "coordinator executed PATH-shadowed python.cmd"
    }
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}

Write-Host "RESULT passed=$script:passed failed=$script:failed"
if ($script:failed -gt 0) { exit 1 }
exit 0
