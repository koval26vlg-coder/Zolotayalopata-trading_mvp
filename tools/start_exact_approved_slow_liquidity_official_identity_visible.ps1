param(
    [switch]$PreflightOnly,
    [switch]$VisibleWorker,
    [switch]$Status,
    [switch]$Stop,
    [string]$RuntimeManifestPath = "",
    [string]$ExecutionManifestPath = "",
    [string]$OutputPath = "",
    [string]$ExpectedRuntimeManifestFileSha256 = "",
    [string]$ExpectedExecutionManifestFileSha256 = "",
    [string]$ParentLauncherCreationUtc = "",
    [string]$ParentLauncherExecutablePath = "",
    [string]$ParentLauncherCommandLineSha256 = "",
    [int]$ParentLauncherPid = 0
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeModule = "trading_mvp.src.slow_liquidity_official_identity_verification"
$autopilotChecker = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$activeRunChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$writerClaimCli = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"
$globalWriterClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$globalWriterClaimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$runId = "slow_liquidity_official_asset_identity_verification_20260813_v1"
$launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\$runId.launch.json"
$launcherCapabilityPath = Join-Path $repoRoot "docs\agent-log\run-gates\$runId.capability.json"

if (-not $RuntimeManifestPath) {
    $RuntimeManifestPath = Join-Path $repoRoot `
        "docs\plans\slow-liquidity-official-identity-runtime-manifest-20260815-v7.json"
}
if (-not $ExecutionManifestPath) {
    $ExecutionManifestPath = Join-Path $repoRoot `
        "docs\plans\slow-liquidity-official-identity-execution-manifest-20260815-v7.json"
}
if (-not $OutputPath) {
    $OutputPath = `
        "E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-official-identity\$runId"
}

function Resolve-ProjectPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "No usable Python runtime is available."
}

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $text = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $text | ConvertFrom-Json -DateKind String
    }
    return $text | ConvertFrom-Json
}

function Test-VisibleConsoleWindow {
    if (-not $IsWindows) { return $false }
    if ($null -eq ("TradingMvp.IdentityVisibleConsoleNative" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace TradingMvp {
    public static class IdentityVisibleConsoleNative {
        [DllImport("kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWindowVisible(IntPtr hWnd);
    }
}
'@
    }
    $consoleWindow = [TradingMvp.IdentityVisibleConsoleNative]::GetConsoleWindow()
    return (
        $consoleWindow -ne [IntPtr]::Zero -and
        [TradingMvp.IdentityVisibleConsoleNative]::IsWindowVisible($consoleWindow)
    )
}

function Initialize-IdentityJobObject {
    if (-not $IsWindows) { throw "Windows Job Object is required." }
    if ($null -eq ("TradingMvp.IdentityJobNative" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace TradingMvp {
    public static class IdentityJobNative {
        [StructLayout(LayoutKind.Sequential)]
        public struct IO_COUNTERS {
            public UInt64 ReadOperationCount, WriteOperationCount, OtherOperationCount;
            public UInt64 ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }
        [StructLayout(LayoutKind.Sequential)]
        public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
            public Int64 PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public UIntPtr Affinity;
            public UInt32 PriorityClass, SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        public static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll")]
        public static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, UInt32 length);
        [DllImport("kernel32.dll")]
        public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")]
        public static extern bool CloseHandle(IntPtr handle);
    }
}
'@
    }
    $job = [TradingMvp.IdentityJobNative]::CreateJobObject([IntPtr]::Zero, $null)
    if ($job -eq [IntPtr]::Zero) { throw "Unable to create identity Job Object." }
    $info = [TradingMvp.IdentityJobNative+JOBOBJECT_EXTENDED_LIMIT_INFORMATION]::new()
    $info.BasicLimitInformation.LimitFlags = 0x00002000
    $size = [Runtime.InteropServices.Marshal]::SizeOf($info)
    $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    try {
        [Runtime.InteropServices.Marshal]::StructureToPtr($info, $buffer, $false)
        if (-not [TradingMvp.IdentityJobNative]::SetInformationJobObject($job, 9, $buffer, $size)) {
            throw "Unable to set KILL_ON_JOB_CLOSE for identity Job Object."
        }
    } catch {
        [TradingMvp.IdentityJobNative]::CloseHandle($job) | Out-Null
        throw
    } finally {
        [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)
    }
    return $job
}

function Add-ProcessToIdentityJob {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$Job,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process
    )
    if (-not [TradingMvp.IdentityJobNative]::AssignProcessToJobObject($Job, $Process.Handle)) {
        throw "Unable to bind identity writer to visible-owner Job Object."
    }
}

function Close-IdentityJob {
    param([IntPtr]$Job)
    if ($Job -ne [IntPtr]::Zero) {
        [TradingMvp.IdentityJobNative]::CloseHandle($Job) | Out-Null
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-JsonCreateNew {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Object
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $raw = ($Object | ConvertTo-Json -Depth 30) + [Environment]::NewLine
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($raw)
    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read
        )
    } catch [System.IO.IOException] {
        throw "Exact identity launch record already exists; duplicate launch is forbidden."
    }
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Object
    )

    $raw = ($Object | ConvertTo-Json -Depth 30) + [Environment]::NewLine
    $temporary = "$Path.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
    try {
        [System.IO.File]::WriteAllText(
            $temporary,
            $raw,
            [System.Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "JSON file is missing: $Path"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $Path
    )
}

function Get-ProcessIdentity {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" `
        -ErrorAction Stop
    if (-not $process) { throw "Process identity is unavailable for PID $ProcessId." }
    $creationUtc = $process.CreationDate.ToUniversalTime().ToString("o")
    $commandLine = [string]$process.CommandLine
    $commandBytes = [System.Text.Encoding]::UTF8.GetBytes($commandLine)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $commandHash = [Convert]::ToHexString(
            $hasher.ComputeHash($commandBytes)
        ).ToLowerInvariant()
    } finally {
        $hasher.Dispose()
    }
    return [ordered]@{
        process_id = [int]$process.ProcessId
        parent_process_id = [int]$process.ParentProcessId
        creation_utc = $creationUtc
        executable_path = [string]$process.ExecutablePath
        command_line_sha256 = $commandHash
    }
}

function Invoke-PythonJson {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $python = Resolve-ProjectPython
    $raw = @(& $python -m $runtimeModule @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = @($raw) -join [Environment]::NewLine
    try {
        $payload = ConvertFrom-JsonPreserveDateStrings -InputJson $text
    } catch {
        throw "Identity runtime did not return valid JSON. Exit=$exitCode"
    }
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "Identity runtime failed: $([string]$payload.reason)"
    }
    return [pscustomobject]@{
        payload = $payload
        exit_code = $exitCode
    }
}

function Start-IdentityRuntimeProcess {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = Resolve-ProjectPython
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.ArgumentList.Add("-m")
    $startInfo.ArgumentList.Add($runtimeModule)
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add([string]$argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        $process.Dispose()
        throw "Identity runtime process did not start."
    }
    return $process
}

function Assert-ExpectedFileHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not $Expected) {
        return
    }
    if ($Expected -cnotmatch '^[0-9a-f]{64}$') {
        throw "$Label expected SHA256 is invalid."
    }
    if ((Get-Sha256 -Path $Path) -cne $Expected) {
        throw "$Label SHA256 mismatch."
    }
}

function Invoke-RuntimePreflight {
    $result = Invoke-PythonJson -AllowFailure -Arguments @(
        "--preflight-execution",
        "--runtime-manifest-path", $RuntimeManifestPath,
        "--execution-manifest-path", $ExecutionManifestPath,
        "--output-path", $OutputPath
    )
    return $result
}

function Invoke-AuthoritativeRuntimePreflight {
    return Invoke-PythonJson -AllowFailure -Arguments @(
        "--preflight-authoritative-execution",
        "--runtime-manifest-path", $RuntimeManifestPath,
        "--execution-manifest-path", $ExecutionManifestPath,
        "--output-path", $OutputPath
    )
}

function Invoke-FullPreflight {
    if ($VisibleWorker) {
        Assert-ExpectedFileHash -Path $RuntimeManifestPath `
            -Expected $ExpectedRuntimeManifestFileSha256 -Label "Runtime manifest"
        Assert-ExpectedFileHash -Path $ExecutionManifestPath `
            -Expected $ExpectedExecutionManifestFileSha256 -Label "Execution manifest"
    }
    $runtime = Invoke-RuntimePreflight
    if ([string]$runtime.payload.status -ne "READY_EXACT_CODE_BOUND_EXECUTION_APPROVAL") {
        return [ordered]@{
            status = "BLOCKED_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
            reason = [string]$runtime.payload.reason
            run_id = $runId
            network_accessed = $false
            identity_output_created = $false
            output_path = [System.IO.Path]::GetFullPath($OutputPath)
        }
    }

    Assert-ExpectedFileHash -Path $RuntimeManifestPath `
        -Expected $ExpectedRuntimeManifestFileSha256 -Label "Runtime manifest"
    Assert-ExpectedFileHash -Path $ExecutionManifestPath `
        -Expected $ExpectedExecutionManifestFileSha256 -Label "Execution manifest"

    $authoritative = Invoke-AuthoritativeRuntimePreflight
    if (
        $authoritative.exit_code -ne 0 -or
        [string]$authoritative.payload.status -ne
            "READY_AUTHORITATIVE_EXACT_CODE_BOUND_EXECUTION"
    ) {
        return [ordered]@{
            status = "BLOCKED_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
            reason = [string]$authoritative.payload.reason
            run_id = $runId
            network_accessed = $false
            identity_output_created = $false
            output_path = [System.IO.Path]::GetFullPath($OutputPath)
        }
    }
    $reasons = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $globalWriterClaimPath) {
        $reasons.Add("global_writer_claim_exists")
    }
    if (Test-Path -LiteralPath $launchRecordPath) {
        $reasons.Add("single_use_launch_record_exists")
    }
    if (Test-Path -LiteralPath $launcherCapabilityPath) {
        $reasons.Add("single_use_launcher_capability_exists")
    }
    if (Test-Path -LiteralPath $OutputPath) {
        $reasons.Add("immutable_output_namespace_exists")
    }
    return [ordered]@{
        status = if ($reasons.Count -eq 0) {
            "READY_FOR_VISIBLE_SINGLE_USE_IDENTITY_RUN"
        } else {
            "BLOCKED"
        }
        reasons = @($reasons)
        run_id = $runId
        runtime_manifest_path = [System.IO.Path]::GetFullPath($RuntimeManifestPath)
        runtime_manifest_file_sha256 = Get-Sha256 -Path $RuntimeManifestPath
        execution_manifest_path = [System.IO.Path]::GetFullPath($ExecutionManifestPath)
        execution_manifest_file_sha256 = Get-Sha256 -Path $ExecutionManifestPath
        output_path = [System.IO.Path]::GetFullPath($OutputPath)
        guard_decision = [string]$authoritative.payload.guard_decision
        policy_hash = [string]$authoritative.payload.policy_hash
        readiness_hash = [string]$authoritative.payload.readiness_hash
        guard_observed_at_utc = [string]$authoritative.payload.guard_observed_at_utc
        network_accessed = $false
        identity_output_created = $false
    }
}

function Invoke-WriterClaim {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $python = Resolve-ProjectPython
    $raw = @(& $python $writerClaimCli @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Global market writer claim failed: $(@($raw) -join ' ')"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $raw
}

function Set-LaunchRecordStatus {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$NewStatus,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $Record.status = $NewStatus
    $Record.message = $Message
    $Record.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    Write-JsonAtomic -Path $launchRecordPath -Object $Record
}

if ($Status) {
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_official_identity_status_v1"
        run_id = $runId
        launch_record = if (Test-Path -LiteralPath $launchRecordPath) {
            Read-JsonFile -Path $launchRecordPath
        } else { $null }
        global_writer_claim = if (Test-Path -LiteralPath $globalWriterClaimPath) {
            Read-JsonFile -Path $globalWriterClaimPath
        } else { $null }
        output_present = Test-Path -LiteralPath $OutputPath
        launcher_capability_present = Test-Path -LiteralPath $launcherCapabilityPath
    } | ConvertTo-Json -Depth 30
    exit 0
}

if ($Stop) {
    if (-not (Test-Path -LiteralPath $launchRecordPath -PathType Leaf)) {
        throw "Exact identity launch record is missing; there is no owned run to stop."
    }
    $record = Read-JsonFile -Path $launchRecordPath
    if ([string]$record.run_id -ne $runId) {
        throw "Identity launch record run_id mismatch."
    }
    if ([string]$record.status -ne "RUNNING") {
        [ordered]@{ status = "NOT_RUNNING"; run_id = $runId } | ConvertTo-Json -Depth 5
        exit 0
    }
    if (-not (Test-Path -LiteralPath $globalWriterClaimPath -PathType Leaf)) {
        throw "Global writer claim is missing; refusing a PID-only stop."
    }
    $claim = Read-JsonFile -Path $globalWriterClaimPath
    $writerPid = [int]$record.writer_pid
    if (
        $writerPid -le 0 -or
        [string]$claim.run_id -ne $runId -or
        [int]$claim.owner_pid -ne [int]$record.visible_terminal_pid -or
        [int]$claim.terminal_pid -ne [int]$record.visible_terminal_pid -or
        [int]$claim.writer_pid -ne $writerPid
    ) {
        throw "Global writer claim does not match the visible identity owner."
    }
    $writerIdentity = Get-ProcessIdentity -ProcessId $writerPid
    if (
        [string]$writerIdentity.creation_utc -cne [string]$record.writer_process_creation_utc -or
        [string]$writerIdentity.executable_path -cne [string]$record.writer_executable_path -or
        [string]$writerIdentity.command_line_sha256 -cne [string]$record.writer_command_line_sha256 -or
        [int]$writerIdentity.parent_process_id -ne [int]$record.visible_terminal_pid
    ) {
        throw "Owned identity process identity mismatch; refusing stop."
    }
    $ownerProcess = Get-Process -Id ([int]$record.visible_terminal_pid) `
        -ErrorAction SilentlyContinue
    if ($ownerProcess) {
        $ownerIdentity = Get-ProcessIdentity -ProcessId ([int]$record.visible_terminal_pid)
        if (
            [string]$ownerIdentity.creation_utc -cne [string]$record.owner_process_creation_utc -or
            [string]$ownerIdentity.executable_path -cne [string]$record.owner_executable_path -or
            [string]$ownerIdentity.command_line_sha256 -cne [string]$record.owner_command_line_sha256
        ) {
            throw "Visible identity owner PID was reused; refusing stop."
        }
    }
    $process = Get-Process -Id $writerPid -ErrorAction SilentlyContinue
    if (-not $process) {
        [ordered]@{ status = "NOT_RUNNING"; run_id = $runId } | ConvertTo-Json -Depth 5
        exit 0
    }
    Stop-Process -Id $process.Id -Force
    [ordered]@{ status = "STOP_REQUESTED"; run_id = $runId; writer_pid = $process.Id } |
        ConvertTo-Json -Depth 5
    exit 0
}

if ($PreflightOnly) {
    try {
        $preflight = Invoke-FullPreflight
        $preflight | ConvertTo-Json -Depth 30 -Compress
        if ([string]$preflight.status -eq "READY_FOR_VISIBLE_SINGLE_USE_IDENTITY_RUN") {
            exit 0
        }
        exit 2
    } catch {
        [ordered]@{
            status = "BLOCKED_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
            reason = $_.Exception.Message
            run_id = $runId
            network_accessed = $false
            identity_output_created = $false
            output_path = [System.IO.Path]::GetFullPath($OutputPath)
        } | ConvertTo-Json -Depth 10 -Compress
        exit 2
    }
}

if (-not $VisibleWorker) {
    $preflight = Invoke-FullPreflight
    if ([string]$preflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE_IDENTITY_RUN") {
        throw "Exact identity run is not authorized: $($preflight.status); $($preflight.reasons -join ',')."
    }
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $parentIdentity = Get-ProcessIdentity -ProcessId $PID
    $arguments = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath,
        "-RuntimeManifestPath", $preflight.runtime_manifest_path,
        "-ExecutionManifestPath", $preflight.execution_manifest_path,
        "-OutputPath", $preflight.output_path,
        "-ExpectedRuntimeManifestFileSha256", $preflight.runtime_manifest_file_sha256,
        "-ExpectedExecutionManifestFileSha256", $preflight.execution_manifest_file_sha256,
        "-ParentLauncherCreationUtc", $parentIdentity.creation_utc,
        "-ParentLauncherExecutablePath", $parentIdentity.executable_path,
        "-ParentLauncherCommandLineSha256", $parentIdentity.command_line_sha256,
        "-ParentLauncherPid", [string]$PID,
        "-VisibleWorker"
    )
    $terminal = Start-Process -FilePath $pwsh -ArgumentList $arguments `
        -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    $record = $null
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if ($terminal.HasExited) {
            throw "Visible identity terminal exited before claiming the exact run."
        }
        if (Test-Path -LiteralPath $launchRecordPath -PathType Leaf) {
            try {
                $candidate = Read-JsonFile -Path $launchRecordPath
                if (
                    [string]$candidate.run_id -eq $runId -and
                    [int]$candidate.visible_terminal_pid -eq $terminal.Id -and
                    [bool]$candidate.terminal_ownership_verified
                ) {
                    $record = $candidate
                    break
                }
            } catch {
                # The visible worker may be between exclusive create and an atomic update.
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $record) {
        throw "Visible identity terminal did not claim the exact run within 30 seconds."
    }
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_official_identity_visible_launch_v1"
        status = "VISIBLE_TERMINAL_LAUNCHED"
        run_id = $runId
        visible_terminal_pid = $terminal.Id
        terminal_ownership_verified = $true
        child_status = [string]$record.status
        launch_record_path = $launchRecordPath
        output_path = $OutputPath
        max_runtime_sec = 600
        hard_output_cap_bytes = 20000000
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
        stop_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Stop"
    } | ConvertTo-Json -Depth 10
    exit 0
}

if ($ParentLauncherPid -le 0 -or -not (Get-Process -Id $ParentLauncherPid -ErrorAction SilentlyContinue)) {
    throw "Visible worker parent ownership is not verified."
}
$parentIdentity = Get-ProcessIdentity -ProcessId $ParentLauncherPid
if (
    -not $ParentLauncherCreationUtc -or
    -not $ParentLauncherExecutablePath -or
    $ParentLauncherCommandLineSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    [string]$parentIdentity.creation_utc -cne $ParentLauncherCreationUtc -or
    [string]$parentIdentity.executable_path -cne $ParentLauncherExecutablePath -or
    [string]$parentIdentity.command_line_sha256 -cne $ParentLauncherCommandLineSha256
) {
    throw "Visible worker parent process identity mismatch."
}
if (-not (Test-VisibleConsoleWindow)) {
    throw "visible_console_not_verified"
}

$preflight = Invoke-FullPreflight
if ([string]$preflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE_IDENTITY_RUN") {
    throw "Visible worker preflight blocked execution: $($preflight.reasons -join ',')."
}

    $launchRecord = [ordered]@{
    schema = "trading_mvp_slow_liquidity_official_identity_launch_v1"
    status = "VISIBLE_WORKER_CLAIMED"
    run_id = $runId
    visible_terminal_pid = $PID
    parent_launcher_pid = $ParentLauncherPid
    parent_launcher_creation_utc = $ParentLauncherCreationUtc
    parent_launcher_executable_path = $ParentLauncherExecutablePath
    parent_launcher_command_line_sha256 = $ParentLauncherCommandLineSha256
    terminal_ownership_verified = $true
    writer_pid = $null
    started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    finished_at_utc = $null
    runtime_manifest_path = $RuntimeManifestPath
    runtime_manifest_file_sha256 = Get-Sha256 -Path $RuntimeManifestPath
    execution_manifest_path = $ExecutionManifestPath
    execution_manifest_file_sha256 = Get-Sha256 -Path $ExecutionManifestPath
    output_path = $OutputPath
    global_writer_claim_path = $globalWriterClaimPath
    global_writer_claim_archive_path = $null
    launcher_capability_path = $launcherCapabilityPath
    owner_process_creation_utc = $null
    owner_executable_path = $null
    owner_command_line_sha256 = $null
    writer_process_creation_utc = $null
    writer_executable_path = $null
    writer_command_line_sha256 = $null
    job_object_kill_on_close = $false
    message = "Visible worker claimed the exact code-bound identity run."
    network_accessed = $false
    identity_output_created = $false
    retry_authorized = $false
}

$claimToken = $null
$claimReleased = $false
$recordOwned = $false
$runtimeProcess = $null
$jobObject = [IntPtr]::Zero
$capabilityCreated = $false
try {
    Write-JsonCreateNew -Path $launchRecordPath -Object $launchRecord
    $recordOwned = $true
    Write-Host "[slow-liquidity-identity] exact visible worker claimed: $runId" `
        -ForegroundColor Cyan

    $claim = Invoke-WriterClaim -Arguments @(
        "claim", "--path", $globalWriterClaimPath,
        "--run-id", $runId,
        "--owner-pid", [string]$PID,
        "--owner-kind", "slow_liquidity_official_identity",
        "--plan-hash", (Read-JsonFile -Path $RuntimeManifestPath).proposal.proposal_hash,
        "--output-namespace", $OutputPath,
        "--terminal-pid", [string]$PID
    )
    $claimToken = [string]$claim.ownership_token

    $jobObject = Initialize-IdentityJobObject
    $launchRecord.job_object_kill_on_close = $true
    $launcherCapabilityToken = (
        [Convert]::ToHexString(
            [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
        )
    ).ToLowerInvariant()

    $runtimeProcess = Start-IdentityRuntimeProcess -Arguments @(
        "--run-approved",
        "--runtime-manifest-path", $RuntimeManifestPath,
        "--execution-manifest-path", $ExecutionManifestPath,
        "--output-path", $OutputPath,
        "--global-writer-claim-path", $globalWriterClaimPath,
        "--owner-pid", [string]$PID,
        "--ownership-token", $claimToken,
        "--writer-claim-wait-sec", "10",
        "--launcher-capability-path", $launcherCapabilityPath,
        "--launcher-capability-token", $launcherCapabilityToken
    )
    Add-ProcessToIdentityJob -Job $jobObject -Process $runtimeProcess
    $null = Invoke-WriterClaim -Arguments @(
        "attach", "--path", $globalWriterClaimPath,
        "--run-id", $runId,
        "--owner-pid", [string]$PID,
        "--ownership-token", $claimToken,
        "--writer-pid", [string]$runtimeProcess.Id
    )
    $launchRecord.writer_pid = $runtimeProcess.Id
    $ownerIdentity = Get-ProcessIdentity -ProcessId $PID
    $writerIdentity = Get-ProcessIdentity -ProcessId $runtimeProcess.Id
    if ([int]$writerIdentity.parent_process_id -ne $PID) {
        throw "Identity runtime is not owned by the visible terminal."
    }
    $launchRecord.owner_process_creation_utc = $ownerIdentity.creation_utc
    $launchRecord.owner_executable_path = $ownerIdentity.executable_path
    $launchRecord.owner_command_line_sha256 = $ownerIdentity.command_line_sha256
    $launchRecord.writer_process_creation_utc = $writerIdentity.creation_utc
    $launchRecord.writer_executable_path = $writerIdentity.executable_path
    $launchRecord.writer_command_line_sha256 = $writerIdentity.command_line_sha256
    $capability = [ordered]@{
        schema = "trading_mvp_slow_liquidity_official_identity_launcher_capability_v1"
        status = "ACTIVE"
        run_id = $runId
        owner_pid = $PID
        writer_pid = $runtimeProcess.Id
        owner_process_creation_utc = $ownerIdentity.creation_utc
        owner_executable_path = $ownerIdentity.executable_path
        owner_command_line_sha256 = $ownerIdentity.command_line_sha256
        writer_process_creation_utc = $writerIdentity.creation_utc
        writer_executable_path = $writerIdentity.executable_path
        writer_command_line_sha256 = $writerIdentity.command_line_sha256
        launcher_path = [System.IO.Path]::GetFullPath($PSCommandPath)
        launcher_file_sha256 = Get-Sha256 -Path $PSCommandPath
        runtime_manifest_file_sha256 = Get-Sha256 -Path $RuntimeManifestPath
        execution_manifest_file_sha256 = Get-Sha256 -Path $ExecutionManifestPath
        output_path = [System.IO.Path]::GetFullPath($OutputPath)
        capability_token_sha256 = (
            [Convert]::ToHexString(
                [System.Security.Cryptography.SHA256]::HashData(
                    [System.Text.Encoding]::ASCII.GetBytes($launcherCapabilityToken)
                )
            )
        ).ToLowerInvariant()
        visible_console_verified = $true
        single_use = $true
        guard_decision = [string]$preflight.guard_decision
        policy_hash = [string]$preflight.policy_hash
        readiness_hash = [string]$preflight.readiness_hash
        guard_observed_at_utc = [string]$preflight.guard_observed_at_utc
        guard_checked_before_writer_claim = $true
        created_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    }
    Write-JsonCreateNew -Path $launcherCapabilityPath -Object $capability
    $capabilityCreated = $true
    Set-LaunchRecordStatus -Record $launchRecord -NewStatus "RUNNING" `
        -Message "Fresh guard passed; single global writer claim acquired."

    $runtimeDeadline = [DateTimeOffset]::UtcNow.AddSeconds(600)
    $nextProgress = [DateTimeOffset]::UtcNow.AddSeconds(5)
    while (-not $runtimeProcess.HasExited) {
        if ([DateTimeOffset]::UtcNow -ge $runtimeDeadline) {
            $runtimeProcess.Kill($true)
            $runtimeProcess.WaitForExit()
            throw "Identity runtime exceeded the exact 600 second cap."
        }
        if ([DateTimeOffset]::UtcNow -ge $nextProgress) {
            $elapsed = [math]::Round(
                600 - ($runtimeDeadline - [DateTimeOffset]::UtcNow).TotalSeconds,
                1
            )
            Write-Host "[slow-liquidity-identity] RUNNING elapsed_sec=$elapsed writer_pid=$($runtimeProcess.Id)"
            $nextProgress = [DateTimeOffset]::UtcNow.AddSeconds(5)
        }
        Start-Sleep -Milliseconds 200
    }
    $runtimeProcess.WaitForExit()
    $runtimeStdout = $runtimeProcess.StandardOutput.ReadToEnd()
    $runtimeStderr = $runtimeProcess.StandardError.ReadToEnd()
    if ($runtimeProcess.ExitCode -ne 0) {
        $controlledReason = "identity_runtime_failed_exit_$($runtimeProcess.ExitCode)"
        try {
            $failure = ConvertFrom-JsonPreserveDateStrings -InputJson $runtimeStderr
            if ([string]$failure.reason) {
                $controlledReason = [string]$failure.reason
            }
            $launchRecord.network_accessed = $failure.network_accessed
            $launchRecord.identity_output_created = $failure.identity_output_created
        } catch {
            # Never persist an uncontrolled stderr payload in the launch record.
        }
        throw $controlledReason
    }
    $runtimePayload = ConvertFrom-JsonPreserveDateStrings -InputJson $runtimeStdout
    $launchRecord.network_accessed = [bool]$runtimePayload.network_accessed
    $launchRecord.identity_output_created = [bool]$runtimePayload.identity_output_created
    $launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    Set-LaunchRecordStatus -Record $launchRecord -NewStatus "COMPLETE" `
        -Message ([string]$runtimePayload.status)
    Write-Host "[slow-liquidity-identity] terminal result: $($runtimePayload.status)" `
        -ForegroundColor Green
} catch {
    if ($runtimeProcess -and -not $runtimeProcess.HasExited) {
        try {
            $runtimeProcess.Kill($true)
            $runtimeProcess.WaitForExit()
        } catch {
            # The writer may already have stopped between the liveness check and kill.
        }
    }
    if ($recordOwned) {
        $launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        $launchRecord.retry_authorized = $false
        Set-LaunchRecordStatus -Record $launchRecord -NewStatus "STOPPED_INCOMPLETE" `
            -Message $_.Exception.Message
    }
    Write-Host "[slow-liquidity-identity] STOPPED_INCOMPLETE; retry is not authorized." `
        -ForegroundColor Red
    throw
} finally {
    if ($jobObject -ne [IntPtr]::Zero) {
        Close-IdentityJob -Job $jobObject
        $jobObject = [IntPtr]::Zero
    }
    if ($capabilityCreated) {
        Remove-Item -LiteralPath $launcherCapabilityPath -Force -ErrorAction SilentlyContinue
    }
    if ($runtimeProcess) {
        $runtimeProcess.Dispose()
    }
    if ($claimToken) {
        try {
            $released = Invoke-WriterClaim -Arguments @(
                "release", "--path", $globalWriterClaimPath,
                "--run-id", $runId,
                "--owner-pid", [string]$PID,
                "--ownership-token", $claimToken,
                "--final-status", [string]$launchRecord.status,
                "--archive-dir", $globalWriterClaimArchiveDir
            )
            $claimReleased = $true
            if ($recordOwned) {
                $launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
                Write-JsonAtomic -Path $launchRecordPath -Object $launchRecord
            }
        } catch {
            Write-Host "[slow-liquidity-identity] writer claim release failed: $($_.Exception.Message)" `
                -ForegroundColor Red
        }
    }
}
