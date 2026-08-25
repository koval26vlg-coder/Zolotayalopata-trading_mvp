param(
    [string]$TaskName = "ZolotyayLopata Listing Strategy Due Coordinator",
    [Parameter(Mandatory = $true)][string]$RegistryPath,
    [Parameter(Mandatory = $true)][string]$ReceiptPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedRegistrySha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedReceiptSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedInstallerSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCoordinatorSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedValidatorSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedControlPlaneGitCommit,
    [string]$CodexAutomationsRoot = "",
    [ValidateRange(1, 86400)][int]$WorkerExitTimeoutSec = 1800,
    [switch]$DryRun,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function Write-InstallBlock {
    param([string]$Status, [string]$Reason, [hashtable]$Additional = @{})
    $payload = [ordered]@{
        status = $Status
        reason = $Reason
        registration_attempted = $false
        execution_performed = $false
    }
    foreach ($entry in $Additional.GetEnumerator()) { $payload[$entry.Key] = $entry.Value }
    $payload | ConvertTo-Json -Depth 40
    exit 2
}

function Get-RawSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant() }
    finally { $sha.Dispose() }
}

if (-not ("ListingStrategyPhysicalPath" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class ListingStrategyPhysicalPath {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes,
        uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        SafeFileHandle file, StringBuilder path, uint pathLength, uint flags);

    public static string Resolve(string path) {
        const uint ShareAll = 0x00000001 | 0x00000002 | 0x00000004;
        const uint OpenExisting = 3;
        const uint BackupSemantics = 0x02000000;
        using (SafeFileHandle handle = CreateFileW(
            path, 0, ShareAll, IntPtr.Zero, OpenExisting, BackupSemantics, IntPtr.Zero)) {
            if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            StringBuilder buffer = new StringBuilder(1024);
            uint length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 0);
            if (length == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (length >= buffer.Capacity) {
                buffer = new StringBuilder((int)length + 1);
                length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 0);
                if (length == 0 || length >= buffer.Capacity) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
            }
            string value = buffer.ToString();
            if (value.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) {
                return @"\\" + value.Substring(8);
            }
            if (value.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase)) {
                return value.Substring(4);
            }
            return value;
        }
    }
}
'@
}

function Get-PhysicalPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath([ListingStrategyPhysicalPath]::Resolve($Path))
}

function Test-PathWithin {
    param([string]$CandidatePath, [string]$ParentPath)
    $candidate = [IO.Path]::GetFullPath($CandidatePath)
    $parent = [IO.Path]::GetFullPath($ParentPath).TrimEnd('\', '/')
    return $candidate.Equals($parent, [StringComparison]::OrdinalIgnoreCase) -or
        $candidate.StartsWith(($parent + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)
}

function Assert-CanonicalPhysicalPath {
    param([string]$Path, [ValidateSet("Leaf", "Container")][string]$PathType, [string]$Label)
    if (-not [IO.Path]::IsPathFullyQualified($Path)) { throw "$Label`_PATH_NOT_ABSOLUTE" }
    $logical = [IO.Path]::GetFullPath($Path)
    if ($logical -cne $Path) { throw "$Label`_PATH_NOT_NORMALIZED" }
    if (-not (Test-Path -LiteralPath $logical -PathType $PathType)) { throw "$Label`_PATH_MISSING" }
    $physical = Get-PhysicalPath -Path $logical
    if (-not $logical.Equals($physical, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label`_PATH_REPARSE_ALIAS:$logical`:$physical"
    }
    return $physical
}

$repoRoot = [IO.Path]::GetFullPath((Resolve-Path (Join-Path $PSScriptRoot "..")).Path)
$installerPath = [IO.Path]::GetFullPath($PSCommandPath)
$coordinatorPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "invoke_listing_strategy_due_coordinator.ps1"))
$validatorPath = [IO.Path]::GetFullPath((Join-Path $repoRoot "trading_mvp\src\canonical_strategy_runtime.py"))
$materializerPath = [IO.Path]::GetFullPath((Join-Path $repoRoot "trading_mvp\src\external_registry_materializer.py"))
$promoterPath = [IO.Path]::GetFullPath((Join-Path $repoRoot "trading_mvp\src\external_registry_promoter.py"))
$gitPath = "C:\Program Files\Git\cmd\git.exe"
if (-not (Test-Path -LiteralPath $gitPath -PathType Leaf)) {
    Write-InstallBlock -Status "BLOCKED_INSTALL_BINDING" -Reason "PINNED_GIT_MISSING"
}

function Invoke-PinnedGit {
    param([string[]]$Arguments, [switch]$AllowNonzero)
    $output = @(& $gitPath @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if (-not $AllowNonzero -and $exitCode -ne 0) { throw "GIT_COMMAND_FAILED:$exitCode`:$text" }
    return [pscustomobject]@{ exit_code = $exitCode; text = $text.Trim() }
}

function Assert-ControlPlaneBinding {
    $physicalRepo = Assert-CanonicalPhysicalPath -Path $repoRoot -PathType Container -Label "CONTROL_PLANE_REPO"
    $physicalInstaller = Assert-CanonicalPhysicalPath -Path $installerPath -PathType Leaf -Label "INSTALLER"
    $physicalCoordinator = Assert-CanonicalPhysicalPath -Path $coordinatorPath -PathType Leaf -Label "COORDINATOR"
    $physicalValidator = Assert-CanonicalPhysicalPath -Path $validatorPath -PathType Leaf -Label "VALIDATOR"
    $topLevel = (Invoke-PinnedGit -Arguments @("-C", $physicalRepo, "rev-parse", "--show-toplevel")).text
    $topLevelPhysical = Get-PhysicalPath -Path $topLevel
    if (-not $physicalRepo.Equals($topLevelPhysical, [StringComparison]::OrdinalIgnoreCase)) {
        throw "CONTROL_PLANE_REPO_NOT_GIT_TOPLEVEL"
    }
    $head = (Invoke-PinnedGit -Arguments @("-C", $physicalRepo, "rev-parse", "HEAD")).text
    if ($head -cne $ExpectedControlPlaneGitCommit) { throw "CONTROL_PLANE_COMMIT_MISMATCH:$head" }
    foreach ($binding in @(
        @{ label = "INSTALLER"; path = $physicalInstaller; expected = $ExpectedInstallerSha256 },
        @{ label = "COORDINATOR"; path = $physicalCoordinator; expected = $ExpectedCoordinatorSha256 },
        @{ label = "VALIDATOR"; path = $physicalValidator; expected = $ExpectedValidatorSha256 }
    )) {
        $actual = Get-RawSha256 -Path $binding.path
        if ($actual -cne $binding.expected) { throw "$($binding.label)_SHA256_MISMATCH:$actual" }
        $relative = [IO.Path]::GetRelativePath($physicalRepo, $binding.path).Replace('\', '/')
        if ($relative.StartsWith("-", [StringComparison]::Ordinal)) { throw "$($binding.label)_GIT_PATH_INVALID" }
        $exists = Invoke-PinnedGit -Arguments @("-C", $physicalRepo, "cat-file", "-e", "$ExpectedControlPlaneGitCommit`:$relative") -AllowNonzero
        if ($exists.exit_code -ne 0) { throw "$($binding.label)_COMMIT_BLOB_MISSING" }
        # Git diff applies clean filters/EOL conversion; only raw blob bytes bind
        # the executable to its declared commit before coordinator invocation.
        $committedSha256 = Get-HistoricalBlobSha256 $physicalRepo $ExpectedControlPlaneGitCommit $relative
        if ($committedSha256 -cne $binding.expected) { throw "$($binding.label)_WORKTREE_DIFFERS_FROM_COMMIT" }
    }
    return [pscustomobject]@{ repo = $physicalRepo; installer = $physicalInstaller; coordinator = $physicalCoordinator; validator = $physicalValidator }
}

function Read-StrictJson {
    param([string]$Path)
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    return ($utf8.GetString([IO.File]::ReadAllBytes($Path)) | ConvertFrom-Json -DateKind String -ErrorAction Stop)
}

function Test-JsonValueEqual {
    param([AllowNull()][object]$Left, [AllowNull()][object]$Right)
    $leftNode = [System.Text.Json.Nodes.JsonNode]::Parse((ConvertTo-Json -InputObject $Left -Depth 100 -Compress))
    $rightNode = [System.Text.Json.Nodes.JsonNode]::Parse((ConvertTo-Json -InputObject $Right -Depth 100 -Compress))
    return [System.Text.Json.Nodes.JsonNode]::DeepEquals($leftNode, $rightNode)
}

function Assert-ExactFields {
    param([object]$Value, [string[]]$Fields, [string]$Reason)
    if ($null -eq $Value -or $Value -isnot [pscustomobject]) { throw $Reason }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($Fields | Sort-Object -CaseSensitive)
    if (-not (Test-JsonValueEqual $actual $expected)) { throw $Reason }
}

function Get-HistoricalBlobSha256 {
    param([string]$Repository, [string]$Commit, [string]$RelativePath)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $gitPath
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in @("-C", $Repository, "cat-file", "blob", "$Commit`:$RelativePath")) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    $bytes = [IO.MemoryStream]::new()
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        if (-not $process.Start()) { throw "HISTORICAL_GIT_START_FAILED" }
        $errorRead = $process.StandardError.ReadToEndAsync()
        $copy = $process.StandardOutput.BaseStream.CopyToAsync($bytes)
        if (-not $process.WaitForExit(15000)) {
            $process.Kill($true)
            $process.WaitForExit()
            throw "HISTORICAL_GIT_TIMEOUT"
        }
        $null = $copy.GetAwaiter().GetResult()
        $errorText = $errorRead.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw "HISTORICAL_GIT_BLOB_UNAVAILABLE:$($process.ExitCode):$errorText" }
        return [Convert]::ToHexString($sha.ComputeHash($bytes.ToArray())).ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $bytes.Dispose()
        $process.Dispose()
    }
}

function Assert-ActiveReceiptBinding {
    param([object]$Registry, [object]$Receipt, [string]$PhysicalRegistry, [string]$PhysicalReceipt)
    Assert-ExactFields -Value $Receipt -Fields @(
        "schema", "status", "decision", "launch_allowed", "publication_id", "publication_directory",
        "registry_path", "receipt_path", "registry_raw_sha256", "active_strategy_id", "parent_lineage",
        "policy_evidence", "active_runtime_binding", "control_plane_git_commit", "control_bindings",
        "canonical_repositories", "validation"
    ) -Reason "ACTIVE_RECEIPT_FIELDS_INVALID"
    if ([string]$Receipt.status -cne "ACTIVATED_PUBLIC_RESEARCH_ONLY" -or [string]$Receipt.decision -cne "ACTIVE_ROUTABLE" -or -not (Test-JsonValueEqual $Receipt.launch_allowed $true)) { throw "RECEIPT_STATUS_INVALID" }
    if ([string]$Registry.schema -cne "zolotyaylopata.canonical_strategy_runtime.v2" -or [string]$Registry.activation_status -cne "ACTIVE_INSTALLED") { throw "ACTIVE_REGISTRY_STATUS_INVALID" }
    $strategyId = [string]$Receipt.active_strategy_id
    if ([string]::IsNullOrWhiteSpace($strategyId) -or $strategyId -cne [string]$Registry.active_strategy_id) { throw "ACTIVE_STRATEGY_ID_MISMATCH" }
    $activeRows = @($Registry.runtimes | Where-Object { [string]$_.runtime_status -ceq "ACTIVE" })
    $routableRows = @($Registry.runtimes | Where-Object { Test-JsonValueEqual $_.scheduler_routable $true })
    if ($activeRows.Count -ne 1 -or $routableRows.Count -ne 1 -or [string]$activeRows[0].strategy_id -cne $strategyId -or [string]$routableRows[0].strategy_id -cne $strategyId) { throw "ACTIVE_RUNTIME_CARDINALITY_INVALID" }
    $runtime = $activeRows[0]
    if ([string]$runtime.activation_readiness -cne "READY_AFTER_ROUTER_MIGRATION" -or -not (Test-JsonValueEqual $runtime.public_data_only $true) -or -not (Test-JsonValueEqual $runtime.live_trading_allowed $false)) { throw "ACTIVE_POLICY_INVALID" }
    $modes = @($runtime.allowed_modes)
    if ($modes.Count -eq 0 -or @($modes | Where-Object { $_ -isnot [string] -or $_ -cnotin @("DISCOVERY", "PAPER_RESEARCH") }).Count -gt 0) { throw "ACTIVE_POLICY_INVALID" }
    $expectedPolicy = [ordered]@{
        source_decision = "STAGED_FAIL_CLOSED"; all_source_bindings_match = $true
        active_runtime_count = 1; routable_runtime_count = 1
        activation_readiness = "READY_AFTER_ROUTER_MIGRATION"
        public_data_only = $true; live_trading_allowed = $false; allowed_modes = $modes
    }
    if (-not (Test-JsonValueEqual $Receipt.policy_evidence $expectedPolicy)) { throw "ACTIVE_POLICY_INVALID" }
    foreach ($field in @("ok", "registry_valid", "launch_allowed")) {
        if (-not (Test-JsonValueEqual $Receipt.validation.$field $true)) { throw "RECEIPT_VALIDATION_INVALID" }
    }
    if ([string]$Receipt.validation.decision -cne "ACTIVE_ROUTABLE" -or [string]$Receipt.validation.registry_raw_sha256 -cne $ExpectedRegistrySha256) { throw "RECEIPT_VALIDATION_INVALID" }
    if ([string]$Receipt.control_plane_git_commit -cne $ExpectedControlPlaneGitCommit) { throw "RECEIPT_CONTROL_PLANE_COMMIT_MISMATCH" }
    $expectedControlFiles = @{
        promoter = $promoterPath; publication_primitive = $materializerPath
        validator = $validatorPath; coordinator = $coordinatorPath; installer = $installerPath
    }
    $controlRows = @($Receipt.control_bindings)
    $controlRoles = @($controlRows | ForEach-Object { [string]$_.role } | Sort-Object -CaseSensitive)
    if (-not (Test-JsonValueEqual $controlRoles @($expectedControlFiles.Keys | Sort-Object -CaseSensitive))) { throw "CONTROL_BINDING_ROLE_SET_INVALID" }
    foreach ($binding in $controlRows) {
        Assert-ExactFields $binding @("role", "path", "git_commit", "head_sha256") "CONTROL_BINDING_FIELDS_INVALID"
        $role = [string]$binding.role
        $expectedPath = [string]$expectedControlFiles[$role]
        if (-not ([string]$binding.path).Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) { throw "CONTROL_BINDING_PATH_MISMATCH:$role" }
        if ([string]$binding.git_commit -cne $ExpectedControlPlaneGitCommit) { throw "CONTROL_BINDING_COMMIT_MISMATCH:$role" }
        $expectedSha = [string]$binding.head_sha256
        if ($expectedSha -cnotmatch '^[0-9a-f]{64}$') { throw "CONTROL_BINDING_SHA256_INVALID:$role" }
        $physical = Assert-CanonicalPhysicalPath $expectedPath Leaf "CONTROL_BINDING"
        if ((Get-RawSha256 $physical) -cne $expectedSha) { throw "CONTROL_BINDING_SHA256_MISMATCH:$role" }
        $relative = [IO.Path]::GetRelativePath($repoRoot, $physical).Replace('\', '/')
        $blob = Invoke-PinnedGit -Arguments @("-C", $repoRoot, "cat-file", "-e", "$ExpectedControlPlaneGitCommit`:$relative") -AllowNonzero
        if ($blob.exit_code -ne 0) { throw "CONTROL_BINDING_COMMIT_BLOB_MISSING:$role" }
        $committedSha256 = Get-HistoricalBlobSha256 $repoRoot $ExpectedControlPlaneGitCommit $relative
        if ($committedSha256 -cne $expectedSha) { throw "CONTROL_BINDING_WORKTREE_DIFFERS_FROM_COMMIT:$role" }
    }
    $runtimeFields = @("strategy_id", "canonical_repo", "canonical_remote_url", "canonical_git_commit", "canonical_plan_path", "canonical_plan_sha256", "canonical_plan_file_sha256", "canonical_plan_id", "canonical_plan_status", "launcher_path", "launcher_sha256", "state_path", "implementation_bindings")
    Assert-ExactFields $Receipt.active_runtime_binding ($runtimeFields + @("state_raw_sha256", "state_status", "next_interval_at_utc")) "ACTIVE_RUNTIME_BINDING_FIELDS_INVALID"
    foreach ($field in $runtimeFields) {
        if (-not (Test-JsonValueEqual $Receipt.active_runtime_binding.$field $runtime.$field)) { throw "ACTIVE_RUNTIME_BINDING_MISMATCH:$field" }
    }
    # State is a promotion-time snapshot, not a hash that freezes future scheduler ticks.
    $snapshotTime = [DateTimeOffset]::MinValue
    if ([string]$Receipt.active_runtime_binding.state_raw_sha256 -cnotmatch '^[0-9a-f]{64}$' -or [string]::IsNullOrWhiteSpace([string]$Receipt.active_runtime_binding.state_status) -or -not [DateTimeOffset]::TryParse([string]$Receipt.active_runtime_binding.next_interval_at_utc, [ref]$snapshotTime)) { throw "ACTIVE_STATE_SNAPSHOT_INVALID" }
    $lineage = $Receipt.parent_lineage
    Assert-ExactFields $lineage @("publication_id", "registry_path", "registry_raw_sha256", "receipt_path", "receipt_raw_sha256", "source_path", "source_git_commit", "source_head_sha256", "materializer_path", "materializer_git_commit", "materializer_head_sha256", "validator_path", "validator_git_commit", "validator_head_sha256") "PARENT_LINEAGE_FIELDS_INVALID"
    $parentRegistry = Assert-CanonicalPhysicalPath ([string]$lineage.registry_path) Leaf "PARENT_REGISTRY"
    $parentReceipt = Assert-CanonicalPhysicalPath ([string]$lineage.receipt_path) Leaf "PARENT_RECEIPT"
    if ((Get-RawSha256 $parentRegistry) -cne [string]$lineage.registry_raw_sha256) { throw "PARENT_REGISTRY_SHA256_MISMATCH" }
    if ((Get-RawSha256 $parentReceipt) -cne [string]$lineage.receipt_raw_sha256) { throw "PARENT_RECEIPT_SHA256_MISMATCH" }
    $parentDirectory = Split-Path -Parent $parentRegistry
    if ((Split-Path -Leaf $parentRegistry) -cne "canonical_strategy_runtime.json" -or (Split-Path -Leaf $parentReceipt) -cne "materialization_receipt.json" -or -not $parentDirectory.Equals((Split-Path -Parent $parentReceipt), [StringComparison]::OrdinalIgnoreCase) -or [string]$lineage.publication_id -cnotmatch '^[0-9a-f]{64}$' -or (Split-Path -Leaf $parentDirectory) -cne [string]$lineage.publication_id) { throw "PARENT_PUBLICATION_PATH_INVALID" }
    foreach ($protectedRepo in @($repoRoot) + @($Registry.runtimes | ForEach-Object { [string]$_.canonical_repo })) {
        if ((Test-PathWithin $parentRegistry $protectedRepo) -or (Test-PathWithin $parentReceipt $protectedRepo)) { throw "PARENT_PUBLICATION_INSIDE_CANONICAL_REPO" }
    }
    if ((Test-PathWithin $PhysicalRegistry $parentDirectory) -or (Test-PathWithin $PhysicalReceipt $parentDirectory)) { throw "ACTIVE_PUBLICATION_INSIDE_PARENT_PUBLICATION" }
    $parentPayload = Read-StrictJson $parentRegistry
    $parentEvidence = Read-StrictJson $parentReceipt
    if ([string]$parentPayload.schema -cne "zolotyaylopata.canonical_strategy_runtime.v1" -or [string]$parentPayload.activation_status -cne "STAGING_NOT_INSTALLED" -or [string]$parentEvidence.schema -cne "zolotyaylopata.external_registry_materialization_receipt.v2" -or [string]$parentEvidence.status -cne "MATERIALIZED_FAIL_CLOSED" -or [string]$parentEvidence.decision -cne "STAGED_FAIL_CLOSED" -or -not (Test-JsonValueEqual $parentEvidence.launch_allowed $false)) { throw "PARENT_PUBLICATION_STATUS_INVALID" }
    foreach ($field in @("publication_id", "registry_path", "registry_raw_sha256", "receipt_path", "source_path", "source_git_commit", "source_head_sha256", "materializer_path", "materializer_git_commit", "materializer_head_sha256", "validator_path", "validator_git_commit", "validator_head_sha256")) {
        if (-not (Test-JsonValueEqual $lineage.$field $parentEvidence.$field)) {
            if ($field -in @("source_git_commit", "materializer_git_commit", "validator_git_commit")) { throw "PARENT_LINEAGE_COMMIT_MISMATCH" }
            throw "PARENT_LINEAGE_MISMATCH:$field"
        }
    }
    foreach ($role in @("source", "materializer", "validator")) {
        $historicalPath = [string]$lineage."${role}_path"
        $historicalCommit = [string]$lineage."${role}_git_commit"
        $historicalSha = [string]$lineage."${role}_head_sha256"
        if ($historicalCommit -cnotmatch '^[0-9a-f]{40}$' -or $historicalSha -cnotmatch '^[0-9a-f]{64}$') { throw "PARENT_LINEAGE_HISTORICAL_IDENTITY_INVALID:$role" }
        if ($role -eq "materializer" -and -not $historicalPath.Equals($materializerPath, [StringComparison]::OrdinalIgnoreCase)) { throw "PARENT_LINEAGE_HISTORICAL_PATH_MISMATCH:$role" }
        if ($role -eq "validator" -and -not $historicalPath.Equals($validatorPath, [StringComparison]::OrdinalIgnoreCase)) { throw "PARENT_LINEAGE_HISTORICAL_PATH_MISMATCH:$role" }
        $physicalHistoricalPath = Assert-CanonicalPhysicalPath $historicalPath Leaf "PARENT_LINEAGE"
        $historicalRepo = (Invoke-PinnedGit -Arguments @("-C", (Split-Path -Parent $physicalHistoricalPath), "rev-parse", "--show-toplevel")).text
        $historicalRepo = Get-PhysicalPath $historicalRepo
        $relative = [IO.Path]::GetRelativePath($historicalRepo, $physicalHistoricalPath).Replace('\', '/')
        if ((Get-HistoricalBlobSha256 $historicalRepo $historicalCommit $relative) -cne $historicalSha) { throw "PARENT_LINEAGE_HISTORICAL_SHA256_MISMATCH:$role" }
    }
    if ([string]$lineage.materializer_git_commit -cne [string]$lineage.validator_git_commit) { throw "PARENT_LINEAGE_CONTROL_COMMIT_MISMATCH" }
    if (-not ([string]$parentEvidence.publication_directory).Equals($parentDirectory, [StringComparison]::OrdinalIgnoreCase)) { throw "PARENT_PUBLICATION_DIRECTORY_MISMATCH" }
    foreach ($field in @("ok", "registry_valid", "all_runtime_bindings_valid")) {
        if (-not (Test-JsonValueEqual $parentEvidence.validation.$field $true)) { throw "PARENT_RECEIPT_VALIDATION_INVALID" }
    }
    if ([string]$parentEvidence.validation.decision -cne "STAGED_FAIL_CLOSED" -or [string]$parentEvidence.validation.registry_raw_sha256 -cne [string]$lineage.registry_raw_sha256 -or -not (Test-JsonValueEqual $parentEvidence.validation.launch_allowed $false)) { throw "PARENT_RECEIPT_VALIDATION_INVALID" }
    if (-not (Test-JsonValueEqual $parentEvidence.canonical_repositories $Receipt.canonical_repositories)) { throw "PARENT_CANONICAL_REPOSITORY_SET_MISMATCH" }
    $parentTime = [DateTimeOffset]::MinValue
    $activeTime = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$parentPayload.generated_at_utc, [ref]$parentTime) -or -not [DateTimeOffset]::TryParse([string]$Registry.generated_at_utc, [ref]$activeTime) -or $activeTime -lt $parentTime) { throw "ACTIVE_GENERATED_AT_INVALID" }
    # Promotion may change activation metadata only; hypothesis, venues, plans and bindings remain identical.
    $parentPayload.schema = "zolotyaylopata.canonical_strategy_runtime.v2"
    $parentPayload.registry_id = "$($parentPayload.registry_id).active.$strategyId"
    $parentPayload.generated_at_utc = $Registry.generated_at_utc
    $parentPayload.activation_status = "ACTIVE_INSTALLED"
    $parentPayload | Add-Member -NotePropertyName active_strategy_id -NotePropertyValue $strategyId
    foreach ($row in $parentPayload.runtimes) {
        $selected = [string]$row.strategy_id -ceq $strategyId
        if ($selected) { $row.runtime_status = "ACTIVE" }
        elseif ([string]$row.runtime_status -cne "RETIRED") { $row.runtime_status = "INACTIVE" }
        $row.scheduler_routable = $selected
    }
    if (-not (Test-JsonValueEqual $parentPayload $Registry)) { throw "ACTIVE_REGISTRY_PARENT_TRANSFORMATION_MISMATCH" }
}

function Assert-PublicationBinding {
    $physicalRegistry = Assert-CanonicalPhysicalPath -Path $RegistryPath -PathType Leaf -Label "REGISTRY"
    $physicalReceipt = Assert-CanonicalPhysicalPath -Path $ReceiptPath -PathType Leaf -Label "RECEIPT"
    if ((Split-Path -Leaf $physicalRegistry) -cne "canonical_strategy_runtime.json") { throw "REGISTRY_FILENAME_INVALID" }
    $registryParent = [IO.Path]::GetFullPath((Split-Path -Parent $physicalRegistry))
    $receiptParent = [IO.Path]::GetFullPath((Split-Path -Parent $physicalReceipt))
    if (-not $registryParent.Equals($receiptParent, [StringComparison]::OrdinalIgnoreCase)) { throw "PUBLICATION_PAIR_DIRECTORY_MISMATCH" }
    $publicationId = Split-Path -Leaf $registryParent
    if ($publicationId -cnotmatch '^[0-9a-f]{64}$') { throw "PUBLICATION_ID_INVALID" }
    $actualRegistrySha = Get-RawSha256 -Path $physicalRegistry
    $actualReceiptSha = Get-RawSha256 -Path $physicalReceipt
    if ($actualRegistrySha -cne $ExpectedRegistrySha256) { throw "REGISTRY_SHA256_MISMATCH:$actualRegistrySha" }
    if ($actualReceiptSha -cne $ExpectedReceiptSha256) { throw "RECEIPT_SHA256_MISMATCH:$actualReceiptSha" }
    $registry = Read-StrictJson -Path $physicalRegistry
    $receipt = Read-StrictJson -Path $physicalReceipt
    $isActive = [string]$receipt.schema -ceq "zolotyaylopata.external_registry_activation_receipt.v1"
    if (-not $isActive -and [string]$receipt.schema -cne "zolotyaylopata.external_registry_materialization_receipt.v2") { throw "RECEIPT_SCHEMA_INVALID" }
    $expectedReceiptFilename = if ($isActive) { "activation_receipt.json" } else { "materialization_receipt.json" }
    if ((Split-Path -Leaf $physicalReceipt) -cne $expectedReceiptFilename) { throw "RECEIPT_FILENAME_INVALID" }
    if ([string]$receipt.publication_id -cne $publicationId) { throw "RECEIPT_PUBLICATION_ID_MISMATCH" }
    if (-not ([string]$receipt.publication_directory).Equals($registryParent, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_PUBLICATION_DIRECTORY_MISMATCH" }
    if (-not ([string]$receipt.registry_path).Equals($physicalRegistry, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_REGISTRY_PATH_MISMATCH" }
    if (-not ([string]$receipt.receipt_path).Equals($physicalReceipt, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_PATH_MISMATCH" }
    if ([string]$receipt.registry_raw_sha256 -cne $ExpectedRegistrySha256) { throw "RECEIPT_REGISTRY_SHA256_MISMATCH" }
    if ($isActive) {
        Assert-ActiveReceiptBinding $registry $receipt $physicalRegistry $physicalReceipt
    } else {
    if ([string]$receipt.status -cne "MATERIALIZED_FAIL_CLOSED" -or [string]$receipt.decision -cne "STAGED_FAIL_CLOSED" -or $receipt.launch_allowed -ne $false) { throw "RECEIPT_STATUS_INVALID" }
    if ([string]$receipt.materializer_git_commit -cne $ExpectedControlPlaneGitCommit -or [string]$receipt.validator_git_commit -cne $ExpectedControlPlaneGitCommit) { throw "RECEIPT_CONTROL_PLANE_COMMIT_MISMATCH" }
    if ([string]$receipt.validator_head_sha256 -cne $ExpectedValidatorSha256) { throw "RECEIPT_VALIDATOR_SHA256_MISMATCH" }
    if (-not ([string]$receipt.validator_path).Equals($validatorPath, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_VALIDATOR_PATH_MISMATCH" }
    $expectedMaterializerSha256 = [string]$receipt.materializer_head_sha256
    if ($expectedMaterializerSha256 -cnotmatch '^[0-9a-f]{64}$') { throw "RECEIPT_MATERIALIZER_SHA256_INVALID" }
    if (-not ([string]$receipt.materializer_path).Equals($materializerPath, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_MATERIALIZER_PATH_MISMATCH" }
    $physicalMaterializer = Assert-CanonicalPhysicalPath -Path $materializerPath -PathType Leaf -Label "MATERIALIZER"
    if ((Get-RawSha256 -Path $physicalMaterializer) -cne $expectedMaterializerSha256) { throw "MATERIALIZER_SHA256_MISMATCH" }
    $materializerRelative = [IO.Path]::GetRelativePath($repoRoot, $physicalMaterializer).Replace('\', '/')
    $materializerBlob = Invoke-PinnedGit -Arguments @("-C", $repoRoot, "cat-file", "-e", "$ExpectedControlPlaneGitCommit`:$materializerRelative") -AllowNonzero
    if ($materializerBlob.exit_code -ne 0) { throw "MATERIALIZER_COMMIT_BLOB_MISSING" }
    $committedMaterializerSha256 = Get-HistoricalBlobSha256 $repoRoot $ExpectedControlPlaneGitCommit $materializerRelative
    if ($committedMaterializerSha256 -cne $expectedMaterializerSha256) { throw "MATERIALIZER_WORKTREE_DIFFERS_FROM_COMMIT" }
    if ($receipt.validation.ok -ne $true -or $receipt.validation.registry_valid -ne $true -or $receipt.validation.all_runtime_bindings_valid -ne $true -or [string]$receipt.validation.decision -cne "STAGED_FAIL_CLOSED" -or [string]$receipt.validation.registry_raw_sha256 -cne $ExpectedRegistrySha256 -or $receipt.validation.launch_allowed -ne $false) { throw "RECEIPT_VALIDATION_INVALID" }
    }
    $canonicalRepos = @($registry.runtimes | ForEach-Object { [string]$_.canonical_repo } | Where-Object { $_ } | Sort-Object -Unique)
    if ($canonicalRepos.Count -lt 1) { throw "REGISTRY_CANONICAL_REPOS_INVALID" }
    $receiptRepos = @($receipt.canonical_repositories)
    if (Test-PathWithin -CandidatePath $physicalRegistry -ParentPath $repoRoot) { throw "REGISTRY_INSIDE_CONTROL_PLANE_REPO" }
    if (Test-PathWithin -CandidatePath $physicalReceipt -ParentPath $repoRoot) { throw "RECEIPT_INSIDE_CONTROL_PLANE_REPO" }
    foreach ($canonicalRepo in $canonicalRepos) {
        $physicalRepo = Assert-CanonicalPhysicalPath -Path $canonicalRepo -PathType Container -Label "CANONICAL_REPO"
        if (Test-PathWithin -CandidatePath $physicalRegistry -ParentPath $physicalRepo) { throw "REGISTRY_INSIDE_CANONICAL_REPO:$physicalRepo" }
        if (Test-PathWithin -CandidatePath $physicalReceipt -ParentPath $physicalRepo) { throw "RECEIPT_INSIDE_CANONICAL_REPO:$physicalRepo" }
        $runtimeCommits = @($registry.runtimes | Where-Object { ([string]$_.canonical_repo).Equals($canonicalRepo, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { [string]$_.canonical_git_commit } | Sort-Object -Unique)
        if ($runtimeCommits.Count -ne 1) { throw "CANONICAL_REPO_COMMIT_AMBIGUOUS:$canonicalRepo" }
        $runtimeTopLevel = (Invoke-PinnedGit -Arguments @("-C", $physicalRepo, "rev-parse", "--show-toplevel")).text
        $runtimeTopLevelPhysical = Get-PhysicalPath -Path $runtimeTopLevel
        if (-not $physicalRepo.Equals($runtimeTopLevelPhysical, [StringComparison]::OrdinalIgnoreCase)) { throw "CANONICAL_REPO_NOT_GIT_TOPLEVEL:$canonicalRepo" }
        $runtimeHead = (Invoke-PinnedGit -Arguments @("-C", $physicalRepo, "rev-parse", "HEAD")).text
        if ($runtimeHead -cne $runtimeCommits[0]) { throw "CANONICAL_REPO_COMMIT_MISMATCH:$canonicalRepo" }
        $matches = @($receiptRepos | Where-Object { ([string]$_.canonical_repo).Equals($canonicalRepo, [StringComparison]::OrdinalIgnoreCase) -and [string]$_.canonical_git_commit -ceq $runtimeCommits[0] })
        if ($matches.Count -ne 1) { throw "RECEIPT_CANONICAL_REPOSITORY_MISMATCH:$canonicalRepo" }
    }
    if ($receiptRepos.Count -ne $canonicalRepos.Count) { throw "RECEIPT_CANONICAL_REPOSITORY_SET_MISMATCH" }
    return [pscustomobject]@{ registry = $physicalRegistry; receipt = $physicalReceipt; payload = $registry; receipt_payload = $receipt; publication_id = $publicationId; is_active = $isActive }
}

try {
    $controlPlane = Assert-ControlPlaneBinding
    $publication = Assert-PublicationBinding
} catch {
    Write-InstallBlock -Status "BLOCKED_INSTALL_BINDING" -Reason ([string]$_.Exception.Message) -Additional @{
        registry_path = $RegistryPath
        receipt_path = $ReceiptPath
    }
}

function Resolve-InstallAutomationRoot {
    param([string]$RequestedRoot, [bool]$AllowTestOverride)
    $profile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if (-not $profile) { throw "USER_PROFILE_UNAVAILABLE" }
    $canonicalRoot = [IO.Path]::GetFullPath((Join-Path $profile ".codex\automations"))
    if (-not $RequestedRoot) { return $canonicalRoot }
    $requested = [IO.Path]::GetFullPath($RequestedRoot)
    if (-not $AllowTestOverride -and -not $requested.Equals($canonicalRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "LEGACY_AUTOMATIONS_OVERRIDE_REQUIRES_DRY_RUN" }
    return $requested
}

try {
    $CodexAutomationsRoot = Resolve-InstallAutomationRoot -RequestedRoot $CodexAutomationsRoot -AllowTestOverride ([bool]$DryRun)
} catch {
    Write-InstallBlock -Status "BLOCKED_LEGACY_AUTOMATIONS" -Reason ([string]$_.Exception.Message)
}
$legacyAutomationIds = @(
    "zolotyaylopata-listing-momentum-monitor",
    "zolotyaylopata-pre-market-perpetual-listing-impulse-monitor",
    "zolotyaylopata-pre-ipo-perpetual-event-monitor"
)
$legacyRecords = [Collections.Generic.List[object]]::new()
$legacyErrors = [Collections.Generic.List[string]]::new()
foreach ($automationId in $legacyAutomationIds) {
    $automationPath = Join-Path (Join-Path $CodexAutomationsRoot $automationId) "automation.toml"
    $record = [ordered]@{ id = $automationId; path = $automationPath; status = $null; config_sha256 = $null; verified = $false; error = $null }
    try {
        if (-not (Test-Path -LiteralPath $automationPath -PathType Leaf)) { throw "automation.toml is missing" }
        $raw = [IO.File]::ReadAllBytes($automationPath)
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($raw)
        # The parsed status and its hash must describe the same read, even when
        # another process rewrites the TOML between this read and the postcheck.
        $record.config_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()
        $idMatches = [regex]::Matches($text, '(?m)^\s*id\s*=\s*"([^"]+)"\s*$')
        $statusMatches = [regex]::Matches($text, '(?m)^\s*status\s*=\s*"([^"]+)"\s*$')
        if ($idMatches.Count -ne 1 -or $statusMatches.Count -ne 1) { throw "id/status cardinality invalid" }
        if ($idMatches[0].Groups[1].Value -cne $automationId) { throw "id mismatch" }
        $record.status = $statusMatches[0].Groups[1].Value
        if ($record.status -cne "PAUSED") { throw "status must be PAUSED, got '$($record.status)'" }
        $record.verified = $true
    } catch {
        $record.error = $_.Exception.Message
        $legacyErrors.Add("$automationId`: $($_.Exception.Message)")
    }
    $legacyRecords.Add([pscustomobject]$record)
}
if ($legacyErrors.Count -gt 0) {
    Write-InstallBlock -Status "BLOCKED_LEGACY_AUTOMATIONS" -Reason "LEGACY_AUTOMATION_TOPOLOGY_INVALID" -Additional @{
        task_name = $TaskName
        coordinator_path = $controlPlane.coordinator
        codex_automations_root = $CodexAutomationsRoot
        legacy_automations = @($legacyRecords)
        validation_errors = @($legacyErrors)
    }
}

function Assert-LegacyAutomationSnapshot {
    foreach ($record in $legacyRecords) {
        if (-not (Test-Path -LiteralPath $record.path -PathType Leaf) -or (Get-RawSha256 -Path $record.path) -cne [string]$record.config_sha256) {
            throw "LEGACY_AUTOMATION_CONFIG_CHANGED:$($record.id)"
        }
    }
}

$pwsh = (Get-Process -Id $PID).Path
if (-not $pwsh -or -not (Test-Path -LiteralPath $pwsh -PathType Leaf)) { Write-InstallBlock -Status "BLOCKED_INSTALL_BINDING" -Reason "PWSH_RUNTIME_UNAVAILABLE" }
$bindingArguments = @(
    "-RegistryPath", $publication.registry,
    "-ReceiptPath", $publication.receipt,
    "-ExpectedRegistrySha256", $ExpectedRegistrySha256,
    "-ExpectedReceiptSha256", $ExpectedReceiptSha256,
    "-ExpectedCoordinatorSha256", $ExpectedCoordinatorSha256,
    "-ExpectedValidatorSha256", $ExpectedValidatorSha256,
    "-ExpectedControlPlaneGitCommit", $ExpectedControlPlaneGitCommit
)
$preflightArguments = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $controlPlane.coordinator, "-PreflightOnly", "-Json", "-WorkerExitTimeoutSec", [string]$WorkerExitTimeoutSec) + $bindingArguments
$preflightOutput = & $pwsh @preflightArguments 2>&1 | Out-String
$preflightExitCode = $LASTEXITCODE
try { $coordinatorPreflight = $preflightOutput | ConvertFrom-Json -DateKind String -ErrorAction Stop }
catch { Write-InstallBlock -Status "BLOCKED_COORDINATOR_PREFLIGHT" -Reason "COORDINATOR_PREFLIGHT_OUTPUT_INVALID" -Additional @{ coordinator_preflight_exit_code = $preflightExitCode; coordinator_preflight_output = $preflightOutput } }
$preflightStatus = if ($publication.is_active) { "ACTIVE_PREFLIGHT_OK" } else { "STAGED_FAIL_CLOSED" }
$preflightReason = if ($publication.is_active) { "PREFLIGHT_ONLY" } else { "NOT_ACTIVATED" }
$preflightInvalid = $preflightExitCode -ne 0 -or [string]$coordinatorPreflight.status -cne $preflightStatus -or [string]$coordinatorPreflight.reason -cne $preflightReason -or -not (Test-JsonValueEqual $coordinatorPreflight.execution_performed $false) -or -not (Test-JsonValueEqual $coordinatorPreflight.launch_allowed ([bool]$publication.is_active)) -or [string]$coordinatorPreflight.registry_raw_sha256 -cne $ExpectedRegistrySha256 -or [string]$coordinatorPreflight.receipt_raw_sha256 -cne $ExpectedReceiptSha256 -or -not (Test-JsonValueEqual $coordinatorPreflight.validator_exit_code 0)
if ($publication.is_active) {
    $preflightInvalid = $preflightInvalid -or [string]$coordinatorPreflight.registry_decision -cne "ACTIVE_ROUTABLE" -or [string]$coordinatorPreflight.active_strategy_id -cne [string]$publication.payload.active_strategy_id
}
if ($preflightInvalid) {
    $reason = if ($publication.is_active) { "COORDINATOR_PREFLIGHT_NOT_ACTIVE_READ_ONLY" } else { "COORDINATOR_PREFLIGHT_NOT_STAGED_FAIL_CLOSED" }
    Write-InstallBlock -Status "BLOCKED_COORDINATOR_PREFLIGHT" -Reason $reason -Additional @{ coordinator_preflight_exit_code = $preflightExitCode; coordinator_preflight = $coordinatorPreflight }
}

try {
    $postControlPlane = Assert-ControlPlaneBinding
    $postPublication = Assert-PublicationBinding
    Assert-LegacyAutomationSnapshot
} catch {
    Write-InstallBlock -Status "BLOCKED_INSTALL_INPUT_CHANGED" -Reason ([string]$_.Exception.Message)
}

function Quote-ActionArgument([string]$Value) { return '"' + $Value.Replace('"', '\"') + '"' }
$actionArguments = @(
    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", (Quote-ActionArgument $postControlPlane.coordinator), "-ScheduledTick", "-Json",
    "-WorkerExitTimeoutSec", [string]$WorkerExitTimeoutSec,
    "-RegistryPath", (Quote-ActionArgument $postPublication.registry),
    "-ReceiptPath", (Quote-ActionArgument $postPublication.receipt),
    "-ExpectedRegistrySha256", $ExpectedRegistrySha256,
    "-ExpectedReceiptSha256", $ExpectedReceiptSha256,
    "-ExpectedCoordinatorSha256", $ExpectedCoordinatorSha256,
    "-ExpectedValidatorSha256", $ExpectedValidatorSha256,
    "-ExpectedControlPlaneGitCommit", $ExpectedControlPlaneGitCommit
) -join " "

if ($DryRun) {
    [ordered]@{
        status = $(if ($postPublication.is_active) { "ACTIVE_DRY_RUN_OK" } else { "STAGED_FAIL_CLOSED" })
        reason = $(if ($postPublication.is_active) { "DRY_RUN_NO_REGISTRATION" } else { "NOT_ACTIVATED" })
        active_strategy_id = $postPublication.payload.active_strategy_id
        task_name = $TaskName
        installer_path = $postControlPlane.installer
        coordinator_path = $postControlPlane.coordinator
        validator_path = $postControlPlane.validator
        registry_path = $postPublication.registry
        receipt_path = $postPublication.receipt
        expected_registry_sha256 = $ExpectedRegistrySha256
        expected_receipt_sha256 = $ExpectedReceiptSha256
        expected_installer_sha256 = $ExpectedInstallerSha256
        expected_coordinator_sha256 = $ExpectedCoordinatorSha256
        expected_validator_sha256 = $ExpectedValidatorSha256
        expected_control_plane_git_commit = $ExpectedControlPlaneGitCommit
        codex_automations_root = $CodexAutomationsRoot
        wake_interval_minutes = 5
        hidden = $true
        model_invocation = $false
        worker_exit_timeout_sec = $WorkerExitTimeoutSec
        action_arguments = $actionArguments
        coordinator_preflight = $coordinatorPreflight
        launch_allowed = [bool]$postPublication.is_active
        execution_performed = $false
        registration_attempted = $false
        legacy_automations = @($legacyRecords)
    } | ConvertTo-Json -Depth 40
    exit 0
}

$action = New-ScheduledTaskAction -Execute $pwsh -Argument $actionArguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval ([TimeSpan]::FromMinutes(5)) -RepetitionDuration ([TimeSpan]::FromDays(3650))
$settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromHours(12)) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
try {
    $finalControlPlane = Assert-ControlPlaneBinding
    $finalPublication = Assert-PublicationBinding
    Assert-LegacyAutomationSnapshot
} catch {
    Write-InstallBlock -Status "BLOCKED_INSTALL_INPUT_CHANGED" -Reason ([string]$_.Exception.Message)
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
[ordered]@{
    status = "INSTALLED"
    task_name = $TaskName
    task_path = $registered.TaskPath
    installer_path = $finalControlPlane.installer
    coordinator_path = $finalControlPlane.coordinator
    validator_path = $finalControlPlane.validator
    registry_path = $finalPublication.registry
    receipt_path = $finalPublication.receipt
    expected_registry_sha256 = $ExpectedRegistrySha256
    expected_receipt_sha256 = $ExpectedReceiptSha256
    expected_installer_sha256 = $ExpectedInstallerSha256
    expected_coordinator_sha256 = $ExpectedCoordinatorSha256
    expected_validator_sha256 = $ExpectedValidatorSha256
    expected_control_plane_git_commit = $ExpectedControlPlaneGitCommit
    wake_interval_minutes = 5
    hidden = $true
    model_invocation = $false
    worker_exit_timeout_sec = $WorkerExitTimeoutSec
    action_execute = $pwsh
    action_arguments = $actionArguments
    coordinator_preflight = $coordinatorPreflight
    registration_attempted = $true
    legacy_automations = @($legacyRecords)
} | ConvertTo-Json -Depth 40
