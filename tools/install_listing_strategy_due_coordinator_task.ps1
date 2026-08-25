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
        $diff = Invoke-PinnedGit -Arguments @("-C", $physicalRepo, "diff", "--quiet", $ExpectedControlPlaneGitCommit, "--", $relative) -AllowNonzero
        if ($diff.exit_code -ne 0) { throw "$($binding.label)_WORKTREE_DIFFERS_FROM_COMMIT" }
    }
    return [pscustomobject]@{ repo = $physicalRepo; installer = $physicalInstaller; coordinator = $physicalCoordinator; validator = $physicalValidator }
}

function Read-StrictJson {
    param([string]$Path)
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    return ($utf8.GetString([IO.File]::ReadAllBytes($Path)) | ConvertFrom-Json -DateKind String -ErrorAction Stop)
}

function Assert-PublicationBinding {
    $physicalRegistry = Assert-CanonicalPhysicalPath -Path $RegistryPath -PathType Leaf -Label "REGISTRY"
    $physicalReceipt = Assert-CanonicalPhysicalPath -Path $ReceiptPath -PathType Leaf -Label "RECEIPT"
    if ((Split-Path -Leaf $physicalRegistry) -cne "canonical_strategy_runtime.json") { throw "REGISTRY_FILENAME_INVALID" }
    if ((Split-Path -Leaf $physicalReceipt) -cne "materialization_receipt.json") { throw "RECEIPT_FILENAME_INVALID" }
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
    if ([string]$receipt.schema -cne "zolotyaylopata.external_registry_materialization_receipt.v2") { throw "RECEIPT_SCHEMA_INVALID" }
    if ([string]$receipt.status -cne "MATERIALIZED_FAIL_CLOSED" -or [string]$receipt.decision -cne "STAGED_FAIL_CLOSED" -or $receipt.launch_allowed -ne $false) { throw "RECEIPT_STATUS_INVALID" }
    if ([string]$receipt.publication_id -cne $publicationId) { throw "RECEIPT_PUBLICATION_ID_MISMATCH" }
    if (-not ([string]$receipt.publication_directory).Equals($registryParent, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_PUBLICATION_DIRECTORY_MISMATCH" }
    if (-not ([string]$receipt.registry_path).Equals($physicalRegistry, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_REGISTRY_PATH_MISMATCH" }
    if (-not ([string]$receipt.receipt_path).Equals($physicalReceipt, [StringComparison]::OrdinalIgnoreCase)) { throw "RECEIPT_PATH_MISMATCH" }
    if ([string]$receipt.registry_raw_sha256 -cne $ExpectedRegistrySha256) { throw "RECEIPT_REGISTRY_SHA256_MISMATCH" }
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
    $materializerDiff = Invoke-PinnedGit -Arguments @("-C", $repoRoot, "diff", "--quiet", $ExpectedControlPlaneGitCommit, "--", $materializerRelative) -AllowNonzero
    if ($materializerDiff.exit_code -ne 0) { throw "MATERIALIZER_WORKTREE_DIFFERS_FROM_COMMIT" }
    if ($receipt.validation.ok -ne $true -or $receipt.validation.registry_valid -ne $true -or $receipt.validation.all_runtime_bindings_valid -ne $true -or [string]$receipt.validation.decision -cne "STAGED_FAIL_CLOSED" -or [string]$receipt.validation.registry_raw_sha256 -cne $ExpectedRegistrySha256 -or $receipt.validation.launch_allowed -ne $false) { throw "RECEIPT_VALIDATION_INVALID" }
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
    return [pscustomobject]@{ registry = $physicalRegistry; receipt = $physicalReceipt; payload = $registry; receipt_payload = $receipt; publication_id = $publicationId }
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

if (-not $CodexAutomationsRoot) {
    $profile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if (-not $profile) { Write-InstallBlock -Status "BLOCKED_LEGACY_AUTOMATIONS" -Reason "USER_PROFILE_UNAVAILABLE" }
    $CodexAutomationsRoot = Join-Path $profile ".codex\automations"
}
$CodexAutomationsRoot = [IO.Path]::GetFullPath($CodexAutomationsRoot)
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
        $record.config_sha256 = Get-RawSha256 -Path $automationPath
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
$preflightArguments = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $controlPlane.coordinator, "-ScheduledTick", "-Json", "-WorkerExitTimeoutSec", [string]$WorkerExitTimeoutSec) + $bindingArguments
$preflightOutput = & $pwsh @preflightArguments 2>&1 | Out-String
$preflightExitCode = $LASTEXITCODE
try { $coordinatorPreflight = $preflightOutput | ConvertFrom-Json -DateKind String -ErrorAction Stop }
catch { Write-InstallBlock -Status "BLOCKED_COORDINATOR_PREFLIGHT" -Reason "COORDINATOR_PREFLIGHT_OUTPUT_INVALID" -Additional @{ coordinator_preflight_exit_code = $preflightExitCode; coordinator_preflight_output = $preflightOutput } }
if ($preflightExitCode -ne 0 -or [string]$coordinatorPreflight.status -cne "STAGED_FAIL_CLOSED" -or [string]$coordinatorPreflight.reason -cne "NOT_ACTIVATED" -or $coordinatorPreflight.execution_performed -ne $false -or $coordinatorPreflight.launch_allowed -ne $false -or [string]$coordinatorPreflight.registry_raw_sha256 -cne $ExpectedRegistrySha256 -or [string]$coordinatorPreflight.receipt_raw_sha256 -cne $ExpectedReceiptSha256 -or [int]$coordinatorPreflight.validator_exit_code -ne 0) {
    Write-InstallBlock -Status "BLOCKED_COORDINATOR_PREFLIGHT" -Reason "COORDINATOR_PREFLIGHT_NOT_STAGED_FAIL_CLOSED" -Additional @{ coordinator_preflight_exit_code = $preflightExitCode; coordinator_preflight = $coordinatorPreflight }
}

try {
    $postControlPlane = Assert-ControlPlaneBinding
    $postPublication = Assert-PublicationBinding
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
        status = "STAGED_FAIL_CLOSED"
        reason = "NOT_ACTIVATED"
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
        launch_allowed = $false
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
