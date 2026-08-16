param(
    [switch]$PreflightOnly,
    [switch]$VisibleWorker,
    [switch]$Status,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcherFileName = "start_exact_approved_slow_liquidity_spot_v2_official_page_discovery_r4_visible.ps1"
$runtimeModule = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_spot_v2_official_page_discovery_r4.py"
$writerClaimCli = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"
$autopilotChecker = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$activeRunChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$planPath = Join-Path $repoRoot "docs\plans\slow-liquidity-spot-v2-official-page-discovery-planonly-20260815-r4.json"
$globalWriterClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$globalWriterClaimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$runId = "slow_liquidity_spot_v2_official_page_discovery_20260815_r4"
$launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\$runId.launch.json"
$outputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-page-discovery\$runId"
$expectedPlanHash = "2f8cb14b747e582c54b1749a5ff2f5955774b427d2792d31b3853af9c3cd5de9"
$expectedPlanFileSha256 = "05187e3be802a5f2d53d00866f342c1a3f4a0c9d29f70932831ec16973203cce"
$maxRuntimeSec = 600
$hardOutputCapBytes = 20000000

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $text = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $text | ConvertFrom-Json -DateKind String
    }
    return $text | ConvertFrom-Json
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

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-VisibleConsoleWindow {
    if (-not $IsWindows) { return $false }
    if ($null -eq ("TradingMvp.SpotV2DiscoveryVisibleConsoleNative" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace TradingMvp {
    public static class SpotV2DiscoveryVisibleConsoleNative {
        [DllImport("kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWindowVisible(IntPtr hWnd);
    }
}
'@
    }
    $consoleWindow = [TradingMvp.SpotV2DiscoveryVisibleConsoleNative]::GetConsoleWindow()
    return (
        $consoleWindow -ne [IntPtr]::Zero -and
        [TradingMvp.SpotV2DiscoveryVisibleConsoleNative]::IsWindowVisible($consoleWindow)
    )
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function New-LaunchRecordExclusive {
    param([Parameter(Mandatory = $true)]$Object)

    $parent = Split-Path -Parent $launchRecordPath
    if (-not (Test-Path -LiteralPath $parent -Type Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $raw = ($Object | ConvertTo-Json -Depth 20) + [Environment]::NewLine
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($raw)
    try {
        $stream = [System.IO.File]::Open(
            $launchRecordPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read
        )
    } catch [System.IO.IOException] {
        throw "Exact launch record already exists; duplicate launch is forbidden."
    }
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Set-LaunchStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Message = ""
    )

    $script:launchRecord.status = $Status
    $script:launchRecord.message = $Message
    $script:launchRecord.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    $script:launchRecord.visible_terminal_pid = $PID
    Write-JsonAtomic -Object $script:launchRecord -Path $launchRecordPath
}

function Test-ProcessAlive {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return $false
    }
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Assert-FrozenPlan {
    if ((Get-Sha256 -Path $planPath) -cne $expectedPlanFileSha256) {
        throw "Frozen discovery plan file SHA256 mismatch."
    }
    $plan = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $planPath
    )
    if (
        [string]$plan.plan_id -cne $runId -or
        [string]$plan.plan_hash -cne $expectedPlanHash -or
        [string]$plan.market -cne "SPOT_USDT" -or
        [bool]$plan.identity_evidence -or
        [string]$plan.mode -cne "PlanOnly"
    ) {
        throw "Frozen discovery plan identity mismatch."
    }
    $raw = Get-Content -Raw -LiteralPath $planPath
    if (
        $raw -match "20260815-v7" -or
        $raw -match "contract\.mexc\.com" -or
        $raw -match "\{BASE\}_USDT" -or
        $raw -match "www\.bing\.com" -or
        $raw -notmatch "OFFICIAL_NEWS_SITEMAP_TITLE_AND_SLUG"
    ) {
        throw "Frozen discovery plan leaked v7 or perp bindings."
    }
    return $plan
}

function Invoke-GuardPreflight {
    $autopilotRaw = @(& pwsh -NoProfile -ExecutionPolicy Bypass -File $autopilotChecker -Json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot guard failed: $(@($autopilotRaw) -join ' ')"
    }
    $autopilot = ConvertFrom-JsonPreserveDateStrings -InputJson $autopilotRaw
    if ([string]$autopilot.status -ne "ACTIVE") {
        throw "Autopilot guard is not ACTIVE: $($autopilot.status)"
    }
    if ($autopilot.stop_new_actions -ne $false) {
        throw "Autopilot guard forbids new actions."
    }
    if ([string]$autopilot.usage.status -ne "AVAILABLE") {
        throw "Weekly telemetry is unavailable or stale."
    }
    if ([double]$autopilot.usage.remaining_percent -le 15.0) {
        throw "Weekly remaining percentage is at or below 15."
    }

    $gateRaw = @(& pwsh -NoProfile -ExecutionPolicy Bypass -File $activeRunChecker -Json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Active-run gate failed: $(@($gateRaw) -join ' ')"
    }
    $gate = ConvertFrom-JsonPreserveDateStrings -InputJson $gateRaw
    if ([string]$gate.status -eq "RUNNING") {
        throw "another_global_writer_is_running"
    }
    if (Test-Path -LiteralPath $globalWriterClaimPath -PathType Leaf) {
        throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS: owner reconciliation is required."
    }
    return [ordered]@{
        autopilot_status = [string]$autopilot.status
        weekly_remaining_percent = [double]$autopilot.usage.remaining_percent
        gate_status = [string]$gate.status
        gate_run_id = [string]$gate.run_id
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    }
}

function Get-ExistingLaunchDisposition {
    if (-not (Test-Path -LiteralPath $launchRecordPath -PathType Leaf)) {
        return $null
    }
    $record = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $launchRecordPath
    )
    if ([string]$record.run_id -ne $runId) {
        throw "Existing launch record has a mismatched run_id."
    }
    $status = [string]$record.status
    if ($status -eq "COMPLETE") {
        return [ordered]@{ status = "ALREADY_COMPLETE"; record = $record }
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "STOPPED_INCOMPLETE is terminal; retry is not authorized."
    }
    if (Test-ProcessAlive -ProcessId ([int]$record.visible_terminal_pid)) {
        return [ordered]@{ status = "ALREADY_RUNNING"; record = $record }
    }
    throw "A nonterminal launch record has no live owner; retry is not authorized."
}

function Invoke-FullPreflight {
    param([switch]$IgnoreOwnLaunchRecord)

    if ((Split-Path -Leaf $PSCommandPath) -ne $launcherFileName) {
        throw "The discovery must run through its exact top-level launcher."
    }
    foreach ($required in @(
        $runtimeModule, $writerClaimCli, $autopilotChecker, $activeRunChecker, $planPath
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required frozen file is missing: $required"
        }
    }
    $null = Assert-FrozenPlan
    if (Test-Path -LiteralPath (Join-Path $outputPath "request-plan.json") -PathType Leaf) {
        throw "Immutable discovery output already exists."
    }
    if (Test-Path -LiteralPath (Join-Path $outputPath "manifest.json") -PathType Leaf) {
        throw "Immutable discovery manifest already exists."
    }
    if (-not $IgnoreOwnLaunchRecord) {
        $existing = Get-ExistingLaunchDisposition
        if ($existing) {
            return [ordered]@{
                schema = "trading_mvp_spot_v2_official_page_discovery_preflight_v1"
                status = [string]$existing.status
                run_id = $runId
                launch_record_path = $launchRecordPath
                output_path = $outputPath
                network_requested = $false
            }
        }
    }
    $guard = Invoke-GuardPreflight
    return [ordered]@{
        schema = "trading_mvp_spot_v2_official_page_discovery_preflight_v1"
        status = "READY_FOR_VISIBLE_SINGLE_USE"
        run_id = $runId
        plan_hash = $expectedPlanHash
        plan_file_sha256 = $expectedPlanFileSha256
        guard = $guard
        launch_record_path = $launchRecordPath
        output_path = $outputPath
        max_runtime_sec = $maxRuntimeSec
        hard_output_cap_bytes = $hardOutputCapBytes
        identity_verdict = $false
        network_requested = $false
        v7_used = $false
    }
}

function New-GlobalWriterClaim {
    $python = Resolve-ProjectPython
    $raw = @(& $python $writerClaimCli `
        "claim" `
        "--path" $globalWriterClaimPath `
        "--run-id" $runId `
        "--owner-pid" ([string]$PID) `
        "--owner-kind" "slow_liquidity_spot_v2_official_page_discovery_r4" `
        "--plan-hash" $expectedPlanHash `
        "--output-namespace" $outputPath `
        "--terminal-pid" ([string]$PID) 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS_OR_FAILED: $(@($raw) -join ' ')"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $raw
}

function Set-GlobalWriterProcess {
    param(
        [Parameter(Mandatory = $true)][string]$OwnershipToken,
        [Parameter(Mandatory = $true)][int]$WriterPid
    )

    $python = Resolve-ProjectPython
    $raw = @(& $python $writerClaimCli `
        "attach" `
        "--path" $globalWriterClaimPath `
        "--run-id" $runId `
        "--owner-pid" ([string]$PID) `
        "--ownership-token" $OwnershipToken `
        "--writer-pid" ([string]$WriterPid) 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Global writer PID attach failed: $(@($raw) -join ' ')"
    }
}

function Remove-GlobalWriterClaim {
    param(
        [Parameter(Mandatory = $true)][string]$OwnershipToken,
        [Parameter(Mandatory = $true)][string]$FinalStatus
    )

    $python = Resolve-ProjectPython
    $raw = @(& $python $writerClaimCli `
        "release" `
        "--path" $globalWriterClaimPath `
        "--run-id" $runId `
        "--owner-pid" ([string]$PID) `
        "--ownership-token" $OwnershipToken `
        "--final-status" $FinalStatus `
        "--archive-dir" $globalWriterClaimArchiveDir 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Global writer claim release failed: $(@($raw) -join ' ')"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $raw
}

function Assert-CompletedOutput {
    $requestPlanPath = Join-Path $outputPath "request-plan.json"
    $manifestPath = Join-Path $outputPath "manifest.json"
    if (-not (Test-Path -LiteralPath $requestPlanPath -PathType Leaf)) {
        throw "Discovery request-plan.json is missing."
    }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Discovery manifest.json is missing."
    }
    $manifest = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $manifestPath
    )
    if ([bool]$manifest.identity_verdict -or [bool]$manifest.identity_evidence) {
        throw "Discovery output claimed an identity verdict."
    }
    if ([bool]$manifest.v7_used -or [bool]$manifest.perp_template_used -or [bool]$manifest.full_catalog_metadata_used) {
        throw "Discovery output claimed v7, perp, or full-catalog metadata usage."
    }
    if ([string]$manifest.plan_hash -cne $expectedPlanHash) {
        throw "Discovery output plan_hash mismatch."
    }
    if ([string]$manifest.status -notin @(
        "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE",
        "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE"
    )) {
        throw "Discovery output status is not an authorized terminal status."
    }
    $files = @(Get-ChildItem -LiteralPath $outputPath -File)
    $totalBytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
    if ($totalBytes -gt $hardOutputCapBytes) {
        throw "Discovery output exceeds the 20 MB cap."
    }
    return [ordered]@{
        status = [string]$manifest.status
        request_plan_count = [int]$manifest.request_plan_count
        unresolved_pairs = @($manifest.unresolved_pairs)
        request_count = [int]$manifest.request_count
        request_plan_sha256 = [string]$manifest.request_plan_sha256
        identity_verdict = $false
        total_bytes = $totalBytes
        manifest_path = $manifestPath
        request_plan_path = $requestPlanPath
    }
}

if ($Status) {
    [ordered]@{
        schema = "trading_mvp_spot_v2_official_page_discovery_status_v1"
        run_id = $runId
        launch_record = if (Test-Path -LiteralPath $launchRecordPath) {
            ConvertFrom-JsonPreserveDateStrings -InputJson (
                Get-Content -Raw -LiteralPath $launchRecordPath
            )
        } else { $null }
        global_writer_claim = if (Test-Path -LiteralPath $globalWriterClaimPath) {
            ConvertFrom-JsonPreserveDateStrings -InputJson (
                Get-Content -Raw -LiteralPath $globalWriterClaimPath
            )
        } else { $null }
        output_present = Test-Path -LiteralPath (Join-Path $outputPath "manifest.json")
    } | ConvertTo-Json -Depth 20
    exit 0
}

if ($Stop) {
    if (-not (Test-Path -LiteralPath $launchRecordPath -PathType Leaf)) {
        throw "Exact discovery launch record is missing; there is no owned run to stop."
    }
    $record = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $launchRecordPath
    )
    if ([string]$record.status -ne "RUNNING") {
        [ordered]@{ status = "NOT_RUNNING"; run_id = $runId } | ConvertTo-Json -Depth 5
        exit 0
    }
    $writerPid = [int]$record.writer_pid
    if ($writerPid -gt 0) {
        Stop-Process -Id $writerPid -Force -ErrorAction SilentlyContinue
    }
    [ordered]@{ status = "STOP_REQUESTED"; run_id = $runId; writer_pid = $writerPid } |
        ConvertTo-Json -Depth 5
    exit 0
}

if ($PreflightOnly) {
    Invoke-FullPreflight | ConvertTo-Json -Depth 20
    exit 0
}

if (-not $VisibleWorker) {
    $preflight = Invoke-FullPreflight
    if ([string]$preflight.status -in @("ALREADY_COMPLETE", "ALREADY_RUNNING")) {
        $preflight | ConvertTo-Json -Depth 20
        exit 0
    }
    if ([string]$preflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE") {
        throw "Visible launch preflight did not authorize the single-use run."
    }
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $terminal = Start-Process `
        -FilePath $pwsh `
        -ArgumentList @(
            "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $PSCommandPath, "-VisibleWorker"
        ) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal `
        -PassThru
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    $ownedRecord = $null
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if ($terminal.HasExited) {
            throw "Visible discovery terminal exited before claiming the exact run."
        }
        if (Test-Path -LiteralPath $launchRecordPath -PathType Leaf) {
            try {
                $candidate = ConvertFrom-JsonPreserveDateStrings -InputJson (
                    Get-Content -Raw -LiteralPath $launchRecordPath
                )
                if (
                    [string]$candidate.run_id -eq $runId -and
                    [int]$candidate.visible_terminal_pid -eq $terminal.Id
                ) {
                    $ownedRecord = $candidate
                    break
                }
            } catch {
                # Child may be between exclusive create and first atomic update.
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ownedRecord) {
        throw "Visible discovery terminal did not claim the exact run within 30 seconds."
    }
    [ordered]@{
        schema = "trading_mvp_spot_v2_official_page_discovery_visible_launch_v1"
        status = "VISIBLE_TERMINAL_LAUNCHED"
        run_id = $runId
        visible_terminal_pid = $terminal.Id
        terminal_ownership_verified = $true
        child_status = [string]$ownedRecord.status
        launch_record_path = $launchRecordPath
        output_path = $outputPath
        max_runtime_sec = $maxRuntimeSec
        hard_output_cap_bytes = $hardOutputCapBytes
        identity_verdict = $false
        v7_used = $false
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
        stop_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Stop"
    } | ConvertTo-Json -Depth 10
    exit 0
}

if (-not (Test-VisibleConsoleWindow)) {
    throw "visible_console_not_verified"
}

$script:launchRecord = [ordered]@{
    schema = "trading_mvp_spot_v2_official_page_discovery_launch_v1"
    status = "VISIBLE_WORKER_CLAIMED"
    run_id = $runId
    visible_terminal_pid = $PID
    terminal_ownership_verified = $true
    started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    plan_path = $planPath
    plan_hash = $expectedPlanHash
    plan_file_sha256 = $expectedPlanFileSha256
    runtime_module_path = $runtimeModule
    launcher_path = $PSCommandPath
    output_path = $outputPath
    max_runtime_sec = $maxRuntimeSec
    hard_output_cap_bytes = $hardOutputCapBytes
    global_writer_claim_path = $globalWriterClaimPath
    writer_pid = $null
    global_writer_claim_archive_path = $null
    final_output = $null
    identity_verdict = $false
    v7_used = $false
    retry_authorized = $false
    message = "Visible worker claimed the exact single-use official-page discovery run."
}

$globalClaimToken = $null
$runtimeProcess = $null
$launchRecordOwned = $false
try {
    New-LaunchRecordExclusive -Object $script:launchRecord
    $launchRecordOwned = $true
    Write-Host "[spot-v2-discovery] visible exact worker claimed: $runId" -ForegroundColor Cyan

    $workerPreflight = Invoke-FullPreflight -IgnoreOwnLaunchRecord
    if ([string]$workerPreflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE") {
        throw "Worker preflight did not authorize execution: $($workerPreflight.status)"
    }
    $script:launchRecord.guard = $workerPreflight.guard
    Set-LaunchStatus -Status "PREFLIGHT_PASSED" -Message "Fresh guard and exact hashes passed."

    $claim = New-GlobalWriterClaim
    $globalClaimToken = [string]$claim.ownership_token
    Set-LaunchStatus -Status "GLOBAL_WRITER_CLAIMED" -Message "Single global writer claim acquired."

    $python = Resolve-ProjectPython
    $outputParent = Split-Path -Parent $outputPath
    if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) {
        New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
    }
    $logPath = Join-Path $outputParent "$runId.visible.log"
    $runtimeProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @(
            $runtimeModule,
            "--run-approved-visible-discovery"
        ) `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError "$logPath.err" `
        -PassThru
    Set-GlobalWriterProcess -OwnershipToken $globalClaimToken -WriterPid $runtimeProcess.Id
    $script:launchRecord.writer_pid = $runtimeProcess.Id
    Set-LaunchStatus -Status "RUNNING" -Message "Public read-only official-page discovery is running."
    Write-Host "[spot-v2-discovery] running; pid=$($runtimeProcess.Id); cap=${maxRuntimeSec}s" -ForegroundColor Green

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $seen = 0
    while (-not $runtimeProcess.HasExited) {
        if ($stopwatch.Elapsed.TotalSeconds -ge $maxRuntimeSec) {
            Stop-Process -Id $runtimeProcess.Id -Force -ErrorAction SilentlyContinue
            throw "Discovery runtime exceeded the exact 600-second cap."
        }
        if (Test-Path -LiteralPath $logPath -PathType Leaf) {
            $lines = @(Get-Content -LiteralPath $logPath)
            if ($lines.Count -gt $seen) {
                foreach ($line in ($lines | Select-Object -Skip $seen)) {
                    Write-Host $line
                }
                $seen = $lines.Count
            }
        }
        Write-Host ("[spot-v2-discovery] elapsed={0:n1}s writer_pid={1}" -f $stopwatch.Elapsed.TotalSeconds, $runtimeProcess.Id)
        Start-Sleep -Seconds 5
        $runtimeProcess.Refresh()
    }
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        $lines = @(Get-Content -LiteralPath $logPath)
        if ($lines.Count -gt $seen) {
            foreach ($line in ($lines | Select-Object -Skip $seen)) {
                Write-Host $line
            }
        }
    }
    if ($runtimeProcess.ExitCode -notin @(0, 2)) {
        throw "Discovery runtime failed with exit code $($runtimeProcess.ExitCode)."
    }

    $completed = Assert-CompletedOutput
    $released = Remove-GlobalWriterClaim `
        -OwnershipToken $globalClaimToken `
        -FinalStatus ([string]$completed.status)
    $globalClaimToken = $null
    $script:launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
    $script:launchRecord.final_output = $completed
    $script:launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    Set-LaunchStatus -Status "COMPLETE" -Message ([string]$completed.status)
    Write-Host "[spot-v2-discovery] $($completed.status); identity_verdict=false; retry=false" -ForegroundColor Green
} catch {
    if ($runtimeProcess -and -not $runtimeProcess.HasExited) {
        try {
            Stop-Process -Id $runtimeProcess.Id -Force -ErrorAction SilentlyContinue
        } catch {
        }
    }
    if ($launchRecordOwned) {
        $script:launchRecord.retry_authorized = $false
        $script:launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        Set-LaunchStatus -Status "STOPPED_INCOMPLETE" -Message $_.Exception.Message
    }
    Write-Host "[spot-v2-discovery] STOPPED_INCOMPLETE; retry is not authorized." -ForegroundColor Red
    throw
} finally {
    if ($globalClaimToken) {
        try {
            $released = Remove-GlobalWriterClaim `
                -OwnershipToken $globalClaimToken `
                -FinalStatus ([string]$script:launchRecord.status)
            if ($launchRecordOwned) {
                $script:launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
                Write-JsonAtomic -Object $script:launchRecord -Path $launchRecordPath
            }
        } catch {
            Write-Host "[spot-v2-discovery] writer claim release failed: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}
