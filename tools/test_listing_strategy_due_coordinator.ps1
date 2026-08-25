param([string]$TestFilter = "")

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$coordinatorPath = Join-Path $PSScriptRoot "invoke_listing_strategy_due_coordinator.ps1"
$installerPath = Join-Path $PSScriptRoot "install_listing_strategy_due_coordinator_task.ps1"
$uninstallerPath = Join-Path $PSScriptRoot "uninstall_listing_strategy_due_coordinator_task.ps1"
$pwshExe = (Get-Process -Id $PID).Path
$script:passed = 0
$script:failed = 0
$script:testRoots = [System.Collections.Generic.List[string]]::new()
$script:externalTestRoots = [System.Collections.Generic.List[string]]::new()
$legacyAutomationIds = @(
    "zolotyaylopata-listing-momentum-monitor",
    "zolotyaylopata-pre-market-perpetual-listing-impulse-monitor",
    "zolotyaylopata-pre-ipo-perpetual-event-monitor"
)

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
    if ($TestFilter -and $Name -notmatch $TestFilter) { return }
    try {
        & $Body
        $script:passed += 1
        Write-Host "PASS $Name" -ForegroundColor Green
    } catch {
        $script:failed += 1
        Write-Host "FAIL $Name :: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Write-TestJson {
    param([string]$Path, $Value)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function New-TestFixture {
    param(
        [datetimeoffset]$NowUtc = [datetimeoffset]"2026-08-20T12:00:00Z",
        [string[]]$DueTracks = @()
    )

    $leaf = ".test_listing_strategy_due_coordinator_" + [guid]::NewGuid().ToString("N")
    $root = Join-Path $PSScriptRoot $leaf
    New-Item -ItemType Directory -Path $root | Out-Null
    $script:testRoots.Add($root)
    $runGateDir = Join-Path $root "run-gates"
    New-Item -ItemType Directory -Path $runGateDir | Out-Null

    $tracks = [ordered]@{
        listing = [ordered]@{
            state_path = Join-Path $runGateDir "listing.json"
            launcher_path = Join-Path $root "listing_launcher.ps1"
        }
        premarket = [ordered]@{
            state_path = Join-Path $runGateDir "premarket.json"
            launcher_path = Join-Path $root "premarket_launcher.ps1"
        }
        preipo = [ordered]@{
            state_path = Join-Path $runGateDir "preipo.json"
            launcher_path = Join-Path $root "preipo_launcher.ps1"
        }
    }
    foreach ($entry in $tracks.GetEnumerator()) {
        $due = $DueTracks -contains $entry.Key
        $next = if ($due) { $NowUtc.AddMinutes(-1) } else { $NowUtc.AddHours(1) }
        Write-TestJson -Path $entry.Value.state_path -Value ([ordered]@{
            schema = "test_track_state_v1"
            status = "IDLE"
            pending_retry = $false
            next_interval_at_utc = $next.ToString("o")
            last_attempt_id = "before-$($entry.Key)"
            last_finished_at_utc = $NowUtc.AddHours(-2).ToString("o")
            worker_pid = $null
        })
    }

    return [pscustomobject]@{
        root = $root
        now = $NowUtc
        tracks = $tracks
        legacy_automations_root = New-LegacyAutomationFixture
        invocation_log = Join-Path $root "invocations.jsonl"
        coordinator_state = Join-Path $runGateDir "coordinator_state.json"
        coordinator_attempts = Join-Path $runGateDir "coordinator_attempts.jsonl"
        coordinator_claim = Join-Path $runGateDir "coordinator.claim.json"
        coordinator_mutex = Join-Path $runGateDir "coordinator.claim.json.mutex"
        claim_archive = Join-Path $runGateDir "claim-archive"
    }
}

function New-LauncherStub {
    param(
        [string]$Path,
        [string]$TrackName,
        [string]$InvocationLog,
        [int]$WorkerDelayMs = 50,
        [string]$CompletionMarker = "",
        [string]$RequiredMarker = "",
        [int]$WorkerPidOverride = 0
    )

    $escapedLog = $InvocationLog.Replace("'", "''")
    $escapedRequiredMarker = $RequiredMarker.Replace("'", "''")
    $escapedCompletionMarker = $CompletionMarker.Replace("'", "''")
    $escapedPwsh = $pwshExe.Replace("'", "''")
    $workerLines = [System.Collections.Generic.List[string]]::new()
    $workerLines.Add("Start-Sleep -Milliseconds $WorkerDelayMs")
    if ($CompletionMarker) {
        $workerLines.Add("[System.IO.File]::WriteAllText('$escapedCompletionMarker', 'done', [System.Text.UTF8Encoding]::new(`$false))")
    }
    $workerCode = $workerLines -join "; "
    $encodedWorker = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($workerCode))

    $workerCreation = if ($WorkerPidOverride -gt 0) {
        "`$workerPid = $WorkerPidOverride"
    } else {
        @"
`$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
`$startInfo.FileName = '$escapedPwsh'
`$startInfo.UseShellExecute = `$false
`$startInfo.CreateNoWindow = `$true
`$startInfo.RedirectStandardOutput = `$true
`$startInfo.RedirectStandardError = `$true
[void]`$startInfo.ArgumentList.Add('-NoProfile')
[void]`$startInfo.ArgumentList.Add('-EncodedCommand')
[void]`$startInfo.ArgumentList.Add('$encodedWorker')
`$worker = [System.Diagnostics.Process]::Start(`$startInfo)
`$workerPid = `$worker.Id
"@
    }

    $stub = @"
param([switch]`$ScheduledTick, [switch]`$Json)
`$ErrorActionPreference = 'Stop'
if (-not `$ScheduledTick -or -not `$Json) { throw 'coordinator must use -ScheduledTick -Json' }
if ('$escapedRequiredMarker' -and -not (Test-Path -LiteralPath '$escapedRequiredMarker')) {
    throw 'previous visible worker did not exit before this launcher was called'
}
[System.IO.File]::AppendAllText('$escapedLog', '{"track":"$TrackName"}' + [Environment]::NewLine, [System.Text.UTF8Encoding]::new(`$false))
$workerCreation
[ordered]@{
    status = 'VISIBLE_TERMINAL_LAUNCHED'
    visible_terminal_pid = `$workerPid
    expected_duration_sec = 10
} | ConvertTo-Json -Compress
"@
    $stub | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function New-StaticLauncherStub {
    param(
        [string]$Path,
        [string]$TrackName,
        [string]$InvocationLog,
        [ValidateSet("NOT_DUE", "BROKEN")]
        [string]$LauncherStatus
    )

    $escapedLog = $InvocationLog.Replace("'", "''")
    @"
param([switch]`$ScheduledTick, [switch]`$Json)
`$ErrorActionPreference = 'Stop'
if (-not `$ScheduledTick -or -not `$Json) { throw 'coordinator must use -ScheduledTick -Json' }
[System.IO.File]::AppendAllText('$escapedLog', '{"track":"$TrackName"}' + [Environment]::NewLine, [System.Text.UTF8Encoding]::new(`$false))
`$payload = [ordered]@{ status = '$LauncherStatus' }
# BROKEN models a rejected, already-exited worker, not an unknown handoff.
if ('$LauncherStatus' -eq 'BROKEN') { `$payload['visible_terminal_pid'] = 2147483647 }
`$payload | ConvertTo-Json -Compress
"@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function New-AlreadyExitedLauncherStub {
    param(
        [string]$Path,
        [string]$TrackName,
        [string]$InvocationLog,
        [string]$StatePath,
        [string]$StateAttemptId,
        [switch]$IncludeExitEvidence,
        [int]$ReportedExitCode = 0,
        [string]$RequiredMarker = "",
        [string]$CompletionMarker = ""
    )

    $escapedLog = $InvocationLog.Replace("'", "''")
    $escapedState = $StatePath.Replace("'", "''")
    $escapedAttempt = $StateAttemptId.Replace("'", "''")
    $escapedRequiredMarker = $RequiredMarker.Replace("'", "''")
    $escapedCompletionMarker = $CompletionMarker.Replace("'", "''")
    $deadPid = 2147483647
    $exitEvidenceBody = if ($IncludeExitEvidence) {
        @"
`$payload['visible_terminal_exit_pid'] = $deadPid
`$payload['visible_terminal_exit_code'] = $ReportedExitCode
`$payload['visible_terminal_exit_attempt_id'] = '$escapedAttempt'
`$payload['visible_terminal_exit_observed_at_utc'] = [datetimeoffset]::UtcNow.ToString('o')
"@
    } else { "" }

    @"
param([switch]`$ScheduledTick, [switch]`$Json)
`$ErrorActionPreference = 'Stop'
if (-not `$ScheduledTick -or -not `$Json) { throw 'coordinator must use -ScheduledTick -Json' }
if ('$escapedRequiredMarker' -and -not (Test-Path -LiteralPath '$escapedRequiredMarker')) {
    throw 'previous visible worker exit evidence was not observed before this launcher was called'
}
[System.IO.File]::AppendAllText('$escapedLog', '{"track":"$TrackName"}' + [Environment]::NewLine, [System.Text.UTF8Encoding]::new(`$false))
`$state = Get-Content -Raw -LiteralPath '$escapedState' | ConvertFrom-Json
`$state.status = 'COMPLETE'
`$state.pending_retry = `$false
`$state.last_attempt_id = '$escapedAttempt'
`$state.last_finished_at_utc = [datetimeoffset]::UtcNow.ToString('o')
`$state.worker_pid = `$null
[System.IO.File]::WriteAllText('$escapedState', (`$state | ConvertTo-Json -Depth 20), [System.Text.UTF8Encoding]::new(`$false))
if ('$escapedCompletionMarker') {
    [System.IO.File]::WriteAllText('$escapedCompletionMarker', 'done', [System.Text.UTF8Encoding]::new(`$false))
}
`$payload = [ordered]@{
    status = 'VISIBLE_TERMINAL_LAUNCHED'
    visible_terminal_pid = $deadPid
}
$exitEvidenceBody
`$payload | ConvertTo-Json -Compress
"@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function New-ClaimSubstitutingLauncher {
    param(
        [string]$Path,
        [string]$TrackName,
        [string]$InvocationLog,
        [string]$CoordinatorClaimPath,
        [string]$ReplacementClaimPath,
        [ValidateSet("VISIBLE_TERMINAL_LAUNCHED", "NOT_DUE")]
        [string]$LauncherStatus,
        [int]$WorkerPid = 0
    )

    $escapedLog = $InvocationLog.Replace("'", "''")
    $escapedClaim = $CoordinatorClaimPath.Replace("'", "''")
    $escapedReplacement = $ReplacementClaimPath.Replace("'", "''")
    $resultBody = if ($LauncherStatus -eq "VISIBLE_TERMINAL_LAUNCHED") {
        if ($WorkerPid -le 0) { throw "VISIBLE_TERMINAL_LAUNCHED fixture requires WorkerPid" }
        @"
[ordered]@{
    status = 'VISIBLE_TERMINAL_LAUNCHED'
    visible_terminal_pid = $WorkerPid
} | ConvertTo-Json -Compress
"@
    } else {
        "[ordered]@{ status = 'NOT_DUE' } | ConvertTo-Json -Compress"
    }

    @"
param([switch]`$ScheduledTick, [switch]`$Json)
`$ErrorActionPreference = 'Stop'
if (-not `$ScheduledTick -or -not `$Json) { throw 'coordinator must use -ScheduledTick -Json' }
[System.IO.File]::AppendAllText('$escapedLog', '{"track":"$TrackName"}' + [Environment]::NewLine, [System.Text.UTF8Encoding]::new(`$false))
[System.IO.File]::Copy('$escapedReplacement', '$escapedClaim', `$true)
$resultBody
"@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Write-ForeignCoordinatorClaim {
    param(
        [string]$Path,
        [string]$RunId,
        [char]$TokenCharacter = 'f'
    )
    $owner = Get-Process -Id $PID
    Write-TestJson -Path $Path -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = $RunId
        owner_pid = $PID
        owner_process_started_at_utc = $owner.StartTime.ToUniversalTime().ToString("o")
        ownership_token = ([string]$TokenCharacter * 64)
        acquired_at_utc = [datetimeoffset]::UtcNow.ToString("o")
        status = "RUNNING"
        active_track = $null
        active_worker_pid = $null
    })
}

function Set-TestTrackWorkerIdentity {
    param(
        [string]$StatePath,
        [int]$WorkerPid,
        [string]$StartField = "",
        [AllowNull()][string]$StartedAtUtc
    )
    $state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
    $state.worker_pid = $WorkerPid
    if ($StartField) {
        if ($state.PSObject.Properties[$StartField]) {
            $state.$StartField = $StartedAtUtc
        } else {
            $state | Add-Member -NotePropertyName $StartField -NotePropertyValue $StartedAtUtc
        }
    }
    Write-TestJson -Path $StatePath -Value $state
}

function Start-TestWorker {
    param(
        [int]$DelayMs,
        [string]$CompletionMarker = "",
        [string]$StatePath = "",
        [string]$AttemptId = "",
        [string]$FinalStatus = "COMPLETE"
    )
    $workerLines = [System.Collections.Generic.List[string]]::new()
    $workerLines.Add("Start-Sleep -Milliseconds $DelayMs")
    if ($CompletionMarker) {
        $escapedMarker = $CompletionMarker.Replace("'", "''")
        $workerLines.Add("[System.IO.File]::WriteAllText('$escapedMarker', 'done', [System.Text.UTF8Encoding]::new(`$false))")
    }
    if ($StatePath) {
        $escapedStatePath = $StatePath.Replace("'", "''")
        $escapedAttemptId = $(if ($AttemptId) { $AttemptId } else { "after-" + [guid]::NewGuid().ToString("N") }).Replace("'", "''")
        $escapedFinalStatus = $FinalStatus.Replace("'", "''")
        $workerLines.Add("`$state = Get-Content -Raw -LiteralPath '$escapedStatePath' | ConvertFrom-Json")
        $workerLines.Add("`$state.status = '$escapedFinalStatus'")
        $workerLines.Add("`$state.last_attempt_id = '$escapedAttemptId'")
        $workerLines.Add("`$state.last_finished_at_utc = [datetimeoffset]::UtcNow.ToString('o')")
        $workerLines.Add("`$state.worker_pid = `$null")
        $workerLines.Add("`$state | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath '$escapedStatePath' -Encoding utf8NoBOM")
    }
    $encodedWorker = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(($workerLines -join "; ")))
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pwshExe
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    [void]$startInfo.ArgumentList.Add("-NoProfile")
    [void]$startInfo.ArgumentList.Add("-EncodedCommand")
    [void]$startInfo.ArgumentList.Add($encodedWorker)
    return [System.Diagnostics.Process]::Start($startInfo)
}

function New-LegacyCoordinatorHarness {
    param(
        [string]$SourcePath,
        [string]$TargetRoot
    )
    $source = Get-Content -Raw -LiteralPath $SourcePath
    $pattern = '(?s)# BEGIN CANONICAL_RUNTIME_REGISTRY_PREFLIGHT.*?# END CANONICAL_RUNTIME_REGISTRY_PREFLIGHT\s*'
    $stripped = [regex]::Replace($source, $pattern, "", 1)
    if ($stripped -ceq $source) {
        throw "canonical registry preflight markers are missing from test source: $SourcePath"
    }
    $target = Join-Path $TargetRoot ("legacy-core-" + [guid]::NewGuid().ToString("N") + ".ps1")
    $stripped | Set-Content -LiteralPath $target -Encoding utf8NoBOM
    return $target
}

function Invoke-Coordinator {
    param(
        $Fixture,
        [int]$WorkerExitTimeoutSec = 5,
        [string]$CoordinatorScriptPath = $coordinatorPath,
        [string]$AutomationsRoot = ""
    )
    $CoordinatorScriptPath = New-LegacyCoordinatorHarness `
        -SourcePath $CoordinatorScriptPath `
        -TargetRoot $Fixture.root
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $CoordinatorScriptPath,
        "-ScheduledTick", "-Json", "-NowUtc", $Fixture.now.ToString("o"),
        "-ListingStatePath", $Fixture.tracks.listing.state_path,
        "-PremarketStatePath", $Fixture.tracks.premarket.state_path,
        "-PreipoStatePath", $Fixture.tracks.preipo.state_path,
        "-ListingLauncherPath", $Fixture.tracks.listing.launcher_path,
        "-PremarketLauncherPath", $Fixture.tracks.premarket.launcher_path,
        "-PreipoLauncherPath", $Fixture.tracks.preipo.launcher_path,
        "-CoordinatorStatePath", $Fixture.coordinator_state,
        "-CoordinatorAttemptsPath", $Fixture.coordinator_attempts,
        "-CoordinatorClaimPath", $Fixture.coordinator_claim,
        "-CoordinatorClaimArchivePath", $Fixture.claim_archive,
        "-WorkerExitTimeoutSec", [string]$WorkerExitTimeoutSec
    )
    if (-not $AutomationsRoot) { $AutomationsRoot = $Fixture.legacy_automations_root }
    $arguments += @("-CodexAutomationsRoot", $AutomationsRoot)
    $output = & $pwshExe @arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    if (-not $output.Trim()) { throw "coordinator returned no output (exit=$exitCode)" }
    try {
        $payload = $output | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "coordinator output is not JSON (exit=$exitCode): $output"
    }
    return [pscustomobject]@{ payload = $payload; exit_code = $exitCode; raw = $output }
}

function Invoke-CoordinatorWithoutScheduledTick {
    param(
        $Fixture,
        [int]$WorkerExitTimeoutSec = 5,
        [string]$CoordinatorScriptPath = $coordinatorPath
    )
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $CoordinatorScriptPath,
        "-Json", "-NowUtc", $Fixture.now.ToString("o"),
        "-ListingStatePath", $Fixture.tracks.listing.state_path,
        "-PremarketStatePath", $Fixture.tracks.premarket.state_path,
        "-PreipoStatePath", $Fixture.tracks.preipo.state_path,
        "-ListingLauncherPath", $Fixture.tracks.listing.launcher_path,
        "-PremarketLauncherPath", $Fixture.tracks.premarket.launcher_path,
        "-PreipoLauncherPath", $Fixture.tracks.preipo.launcher_path,
        "-CoordinatorStatePath", $Fixture.coordinator_state,
        "-CoordinatorAttemptsPath", $Fixture.coordinator_attempts,
        "-CoordinatorClaimPath", $Fixture.coordinator_claim,
        "-CoordinatorClaimArchivePath", $Fixture.claim_archive,
        "-WorkerExitTimeoutSec", [string]$WorkerExitTimeoutSec
    )
    $arguments += @("-CodexAutomationsRoot", $Fixture.legacy_automations_root)
    $output = & $pwshExe @arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    if (-not $output.Trim()) { throw "coordinator returned no output (exit=$exitCode)" }
    try {
        $payload = $output | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "coordinator output is not JSON (exit=$exitCode): $output"
    }
    return [pscustomobject]@{ payload = $payload; exit_code = $exitCode; raw = $output }
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function New-LegacyAutomationFixture {
    param(
        [hashtable]$Statuses = @{},
        [hashtable]$EmbeddedIds = @{},
        [string[]]$OmitIds = @()
    )
    $leaf = ".test_listing_strategy_due_coordinator_" + [guid]::NewGuid().ToString("N")
    $root = Join-Path $PSScriptRoot $leaf
    New-Item -ItemType Directory -Path $root | Out-Null
    $script:testRoots.Add($root)
    foreach ($id in $legacyAutomationIds) {
        if ($OmitIds -contains $id) { continue }
        $directory = Join-Path $root $id
        New-Item -ItemType Directory -Path $directory | Out-Null
        $status = if ($Statuses.ContainsKey($id)) { [string]$Statuses[$id] } else { "PAUSED" }
        $embeddedId = if ($EmbeddedIds.ContainsKey($id)) { [string]$EmbeddedIds[$id] } else { $id }
        @"
version = 1
id = "$embeddedId"
kind = "cron"
status = "$status"
"@ | Set-Content -LiteralPath (Join-Path $directory "automation.toml") -Encoding utf8NoBOM
    }
    return $root
}

function Invoke-InstallerDryRun {
    param(
        [string]$AutomationsRoot,
        [switch]$CorruptRuntimeBinding,
        [switch]$UsePublicationJunction,
        [switch]$TamperReceiptAfterHash,
        [switch]$TamperInstallerAfterHash
    )
    $taskName = "ZolotyayLopata Coordinator Test " + [guid]::NewGuid().ToString("N")
    $externalRoot = Join-Path ([IO.Path]::GetTempPath()) ("listing-coordinator-installer-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $externalRoot | Out-Null
    $script:externalTestRoots.Add($externalRoot)
    $git = "C:\Program Files\Git\cmd\git.exe"
    $python = "C:\Program Files\Python313\python.exe"
    $controlPlane = Join-Path $externalRoot "control-plane"
    $controlTools = Join-Path $controlPlane "tools"
    $controlSrc = Join-Path $controlPlane "trading_mvp\src"
    New-Item -ItemType Directory -Path $controlTools -Force | Out-Null
    New-Item -ItemType Directory -Path $controlSrc -Force | Out-Null
    Copy-Item -LiteralPath $installerPath -Destination (Join-Path $controlTools "install_listing_strategy_due_coordinator_task.ps1")
    Copy-Item -LiteralPath $coordinatorPath -Destination (Join-Path $controlTools "invoke_listing_strategy_due_coordinator.ps1")
    Copy-Item -LiteralPath (Join-Path $repoRoot "trading_mvp\src\canonical_strategy_runtime.py") -Destination (Join-Path $controlSrc "canonical_strategy_runtime.py")
    Copy-Item -LiteralPath (Join-Path $repoRoot "trading_mvp\src\external_registry_materializer.py") -Destination (Join-Path $controlSrc "external_registry_materializer.py")
    & $git -C $controlPlane init --quiet
    & $git -C $controlPlane config core.autocrlf false
    & $git -C $controlPlane config user.email "coordinator-tests@example.invalid"
    & $git -C $controlPlane config user.name "Coordinator Tests"
    & $git -C $controlPlane add tools trading_mvp
    & $git -C $controlPlane commit --quiet -m "committed control plane fixture"
    $controlCommit = (& $git -C $controlPlane rev-parse HEAD).Trim()

    $runtimeRepo = Join-Path $externalRoot "runtime"
    New-Item -ItemType Directory -Path $runtimeRepo | Out-Null
    & $git -C $runtimeRepo init --quiet
    & $git -C $runtimeRepo config core.autocrlf false
    & $git -C $runtimeRepo config user.email "coordinator-tests@example.invalid"
    & $git -C $runtimeRepo config user.name "Coordinator Tests"
    & $git -C $runtimeRepo remote add origin "https://example.invalid/runtime.git"
    $workerPath = Join-Path $runtimeRepo "worker.py"
    $launcherPath = Join-Path $runtimeRepo "launcher.ps1"
    $planPath = Join-Path $runtimeRepo "plan.json"
    "def run():`n    return 'fixture'`n" | Set-Content -LiteralPath $workerPath -Encoding utf8NoBOM
    "Write-Output 'fixture'`n" | Set-Content -LiteralPath $launcherPath -Encoding utf8NoBOM
    [ordered]@{
        schema = "fixture_plan_v1"
        plan_id = "fixture_plan_20260825_v1"
        status = "READY_FOR_OFFLINE_VALIDATION"
        implementation = [ordered]@{ files = @([ordered]@{ role = "worker"; repo_path = "worker.py"; sha256 = (Get-FileSha256 $workerPath) }) }
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $planPath -Encoding utf8NoBOM
    $planHasher = 'import hashlib,json,sys; p=json.load(open(sys.argv[1],encoding="utf-8-sig")); u=dict(p); u.pop("plan_hash",None); p["plan_hash"]=hashlib.sha256(json.dumps(u,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(); open(sys.argv[1],"w",encoding="utf-8",newline="\n").write(json.dumps(p,ensure_ascii=False,indent=2)+"\n")'
    & $python -c $planHasher $planPath
    & $git -C $runtimeRepo add worker.py launcher.ps1 plan.json
    & $git -C $runtimeRepo commit --quiet -m "runtime fixture"
    $runtimeCommit = (& $git -C $runtimeRepo rev-parse HEAD).Trim()
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json

    $publicationId = "a" * 64
    $publicationDirectory = Join-Path $externalRoot $publicationId
    New-Item -ItemType Directory -Path $publicationDirectory | Out-Null
    $externalRegistryPath = Join-Path $publicationDirectory "canonical_strategy_runtime.json"
    $externalReceiptPath = Join-Path $publicationDirectory "materialization_receipt.json"
    [ordered]@{
        schema = "zolotyaylopata.canonical_strategy_runtime.v1"
        registry_id = "fixture_external_registry_v1"
        generated_at_utc = "2026-08-25T17:00:00Z"
        activation_status = "STAGING_NOT_INSTALLED"
        canonical_owners = @([ordered]@{ strategy_id = "fixture_runtime"; namespace_prefix = "listing.fixture.runtime"; scope = "fixture_scope"; venues = @("fixture") })
        runtimes = @([ordered]@{
            strategy_id = "fixture_runtime"; track_class = "fixture_track"; runtime_status = "INACTIVE"; activation_readiness = "STAGED_ONLY"
            namespace_prefix = "listing.fixture.runtime"; scope = "fixture_scope"; venues = @("fixture")
            canonical_repo = $runtimeRepo; canonical_remote_url = "https://example.invalid/runtime.git"; canonical_git_commit = $runtimeCommit
            canonical_plan_path = $planPath; canonical_plan_sha256 = [string]$plan.plan_hash; canonical_plan_file_sha256 = (Get-FileSha256 $planPath)
            canonical_plan_id = [string]$plan.plan_id; canonical_plan_status = [string]$plan.status
            launcher_path = $launcherPath; launcher_sha256 = (Get-FileSha256 $launcherPath); scheduler_routable = $false
            allowed_modes = @("DISCOVERY"); state_path = (Join-Path $runtimeRepo "state.json"); ledger_path = (Join-Path $runtimeRepo "attempts.jsonl")
            public_data_only = $true; live_trading_allowed = $false
            implementation_bindings = @([ordered]@{ role = "worker"; path = $workerPath; sha256 = (Get-FileSha256 $workerPath) })
            supersedes = @(); retired_aliases = @()
        })
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $externalRegistryPath -Encoding utf8NoBOM
    if ($CorruptRuntimeBinding) {
        $corruptRegistry = Get-Content -Raw -LiteralPath $externalRegistryPath | ConvertFrom-Json
        $corruptRegistry.runtimes[0].implementation_bindings[0].sha256 = "f" * 64
        $corruptRegistry | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $externalRegistryPath -Encoding utf8NoBOM
    }
    $expectedRegistrySha = Get-FileSha256 $externalRegistryPath
    $committedCoordinatorPath = Join-Path $controlTools "invoke_listing_strategy_due_coordinator.ps1"
    $committedValidatorPath = Join-Path $controlSrc "canonical_strategy_runtime.py"
    $committedMaterializerPath = Join-Path $controlSrc "external_registry_materializer.py"
    [ordered]@{
        schema = "zolotyaylopata.external_registry_materialization_receipt.v2"; status = "MATERIALIZED_FAIL_CLOSED"; decision = "STAGED_FAIL_CLOSED"; launch_allowed = $false
        publication_id = $publicationId; publication_directory = $publicationDirectory; source_path = (Join-Path $controlPlane "source.json"); source_git_commit = $controlCommit; source_head_sha256 = ("0" * 64)
        materializer_path = $committedMaterializerPath; materializer_git_commit = $controlCommit; materializer_head_sha256 = (Get-FileSha256 $committedMaterializerPath)
        validator_path = $committedValidatorPath; validator_git_commit = $controlCommit; validator_head_sha256 = (Get-FileSha256 $committedValidatorPath)
        registry_path = $externalRegistryPath; receipt_path = $externalReceiptPath; registry_raw_sha256 = $expectedRegistrySha
        canonical_repositories = @([ordered]@{ canonical_repo = $runtimeRepo; canonical_git_commit = $runtimeCommit })
        validation = [ordered]@{
            ok = $true
            registry_valid = $true
            all_runtime_bindings_valid = $true
            decision = "STAGED_FAIL_CLOSED"
            registry_raw_sha256 = $expectedRegistrySha
            launch_allowed = $false
        }
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $externalReceiptPath -Encoding utf8NoBOM
    $expectedReceiptSha = Get-FileSha256 $externalReceiptPath
    if ($TamperReceiptAfterHash) {
        [IO.File]::AppendAllText($externalReceiptPath, " ", [Text.UTF8Encoding]::new($false))
    }
    $expectedCoordinatorSha = Get-FileSha256 $committedCoordinatorPath
    $expectedValidatorSha = Get-FileSha256 $committedValidatorPath
    $fixtureInstallerPath = Join-Path $controlTools "install_listing_strategy_due_coordinator_task.ps1"
    $expectedInstallerSha = Get-FileSha256 $fixtureInstallerPath
    if ($TamperInstallerAfterHash) {
        [IO.File]::AppendAllText(
            $fixtureInstallerPath,
            "`n# tampered after committed binding`n",
            [Text.UTF8Encoding]::new($false)
        )
    }
    $boundRegistryPath = $externalRegistryPath
    $boundReceiptPath = $externalReceiptPath
    if ($UsePublicationJunction) {
        $publicationAlias = Join-Path $externalRoot ("b" * 64)
        $junction = & "C:\Windows\System32\cmd.exe" /d /c mklink /J $publicationAlias $publicationDirectory 2>&1
        if ($LASTEXITCODE -ne 0) { throw "failed to create publication junction: $junction" }
        $boundRegistryPath = Join-Path $publicationAlias "canonical_strategy_runtime.json"
        $boundReceiptPath = Join-Path $publicationAlias "materialization_receipt.json"
    }
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $fixtureInstallerPath,
        "-DryRun", "-Json", "-TaskName", $taskName,
        "-RegistryPath", $boundRegistryPath,
        "-ReceiptPath", $boundReceiptPath,
        "-ExpectedRegistrySha256", $expectedRegistrySha,
        "-ExpectedInstallerSha256", $expectedInstallerSha,
        "-ExpectedCoordinatorSha256", $expectedCoordinatorSha,
        "-ExpectedReceiptSha256", $expectedReceiptSha,
        "-ExpectedValidatorSha256", $expectedValidatorSha,
        "-ExpectedControlPlaneGitCommit", $controlCommit,
        "-CodexAutomationsRoot", $AutomationsRoot
    )
    $output = & $pwshExe @arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    try {
        $payload = $output | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "installer output is not JSON (exit=$exitCode): $output"
    }
    return [pscustomobject]@{
        payload = $payload
        exit_code = $exitCode
        raw = $output
        task_name = $taskName
        registry_path = $boundRegistryPath
        receipt_path = $boundReceiptPath
        registry_sha256 = $expectedRegistrySha
        receipt_sha256 = $expectedReceiptSha
        coordinator_path = $committedCoordinatorPath
        coordinator_sha256 = $expectedCoordinatorSha
        installer_sha256 = $expectedInstallerSha
        validator_sha256 = $expectedValidatorSha
        control_plane_commit = $controlCommit
    }
}

function Assert-ScheduledTickRejectsLegacyCaseVariant {
    param(
        [ValidateSet("status", "id")]
        [string]$Field,
        [string]$Value
    )

    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $targetId = $legacyAutomationIds[1]
    $statuses = @{}
    $embeddedIds = @{}
    if ($Field -ceq "status") {
        $statuses[$targetId] = $Value
    } else {
        $embeddedIds[$targetId] = $Value
    }
    $automationsRoot = New-LegacyAutomationFixture -Statuses $statuses -EmbeddedIds $embeddedIds

    $trackHashes = @{}
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        $trackHashes[$entry.Key] = Get-FileSha256 $entry.Value.state_path
    }
    $automationHashes = @{}
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        $automationHashes[$id] = Get-FileSha256 $path
    }

    $result = Invoke-Coordinator -Fixture $fixture -AutomationsRoot $automationsRoot

    Assert-Equal $result.exit_code 2 "$Field case variant '$Value' must block scheduled tick: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_LEGACY_AUTOMATIONS" "$Field case variant '$Value' passed scheduled topology validation"
    Assert-Equal $result.payload.reason "LEGACY_AUTOMATION_TOPOLOGY_INVALID" "$Field case variant '$Value' lost the topology reason"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "$Field case variant '$Value' called a launcher"
    foreach ($path in @(
        $fixture.coordinator_state,
        $fixture.coordinator_attempts,
        $fixture.coordinator_claim,
        $fixture.coordinator_mutex,
        $fixture.claim_archive
    )) {
        Assert-True (-not (Test-Path -LiteralPath $path)) "$Field case variant '$Value' wrote coordinator artifact: $path"
    }
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        Assert-Equal (Get-FileSha256 $entry.Value.state_path) $trackHashes[$entry.Key] "$Field case variant '$Value' mutated $($entry.Key) state"
    }
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        Assert-Equal (Get-FileSha256 $path) $automationHashes[$id] "$Field case variant '$Value' mutated $id"
    }
}

function Assert-InstallerRejectsLegacyCaseVariant {
    param(
        [ValidateSet("status", "id")]
        [string]$Field,
        [string]$Value
    )

    $targetId = $legacyAutomationIds[1]
    $statuses = @{}
    $embeddedIds = @{}
    if ($Field -ceq "status") {
        $statuses[$targetId] = $Value
    } else {
        $embeddedIds[$targetId] = $Value
    }
    $automationsRoot = New-LegacyAutomationFixture -Statuses $statuses -EmbeddedIds $embeddedIds
    $automationHashes = @{}
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        $automationHashes[$id] = Get-FileSha256 $path
    }

    $result = Invoke-InstallerDryRun -AutomationsRoot $automationsRoot

    Assert-Equal $result.exit_code 2 "$Field case variant '$Value' must block installer dry-run: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_LEGACY_AUTOMATIONS" "$Field case variant '$Value' passed installer topology validation"
    Assert-Equal $result.payload.reason "LEGACY_AUTOMATION_TOPOLOGY_INVALID" "$Field case variant '$Value' lost the installer topology reason"
    Assert-Equal $result.payload.registration_attempted $false "$Field case variant '$Value' attempted Scheduled Task registration"
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        Assert-Equal (Get-FileSha256 $path) $automationHashes[$id] "$Field case variant '$Value' mutated $id during installer dry-run"
    }
}

$legacyCaseVariants = @(
    [pscustomobject]@{ name = "lowercase status"; field = "status"; value = "paused" },
    [pscustomobject]@{ name = "mixed-case status"; field = "status"; value = "Paused" },
    [pscustomobject]@{ name = "uppercase id"; field = "id"; value = $legacyAutomationIds[1].ToUpperInvariant() },
    [pscustomobject]@{ name = "mixed-case id"; field = "id"; value = "Zolotyaylopata-pre-market-perpetual-listing-impulse-monitor" }
)

Invoke-Test "production files are present" {
    Assert-True (Test-Path -LiteralPath $coordinatorPath -PathType Leaf) "coordinator is missing"
    Assert-True (Test-Path -LiteralPath $installerPath -PathType Leaf) "installer is missing"
    Assert-True (Test-Path -LiteralPath $uninstallerPath -PathType Leaf) "uninstaller is missing"
}

Invoke-Test "default worker timeout covers two sequential bounded spot children plus overhead" {
    $coordinator = Get-Content -Raw -LiteralPath $coordinatorPath
    Assert-True ($coordinator -match '\[int\]\$WorkerExitTimeoutSec\s*=\s*1800') "coordinator default timeout is not 1800 seconds"
    $root = New-LegacyAutomationFixture
    $result = Invoke-InstallerDryRun -AutomationsRoot $root
    Assert-Equal $result.exit_code 0 "timeout dry-run fixture failed: $($result.raw)"
    Assert-Equal $result.payload.worker_exit_timeout_sec 1800 "installer timeout differs from coordinator default"
    Assert-True ([string]$result.payload.action_arguments -match '-WorkerExitTimeoutSec\s+1800(?:\s|$)') "scheduled action does not bind the 1800-second timeout"
}

Invoke-Test "direct due invocation without ScheduledTick is read-only NO_EXECUTION" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $trackHashes = @{}
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        $trackHashes[$entry.Key] = Get-FileSha256 $entry.Value.state_path
    }

    $result = Invoke-CoordinatorWithoutScheduledTick -Fixture $fixture

    Assert-Equal $result.exit_code 2 "direct invocation without ScheduledTick must fail closed: $($result.raw)"
    Assert-Equal $result.payload.status "NO_EXECUTION" "direct invocation did not return NO_EXECUTION"
    Assert-Equal $result.payload.reason "SCHEDULED_TICK_REQUIRED" "direct invocation did not expose the missing ScheduledTick guard"
    Assert-Equal $result.payload.execution_performed $false "direct invocation falsely reported execution"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "direct invocation called a launcher"
    foreach ($path in @(
        $fixture.coordinator_state,
        $fixture.coordinator_attempts,
        $fixture.coordinator_claim,
        $fixture.coordinator_mutex,
        $fixture.claim_archive
    )) {
        Assert-True (-not (Test-Path -LiteralPath $path)) "direct invocation wrote coordinator artifact: $path"
    }
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        Assert-Equal (Get-FileSha256 $entry.Value.state_path) $trackHashes[$entry.Key] "direct invocation mutated $($entry.Key) state"
    }
}

Invoke-Test "NOT_DUE is read-only and creates no claim, state, attempts, archive, or launcher call" {
    $fixture = New-TestFixture
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $before = @{}
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        $before[$entry.Key] = Get-FileSha256 $entry.Value.state_path
    }
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 0 "NOT_DUE must exit zero"
    Assert-Equal $result.payload.status "NOT_DUE" "unexpected coordinator status"
    Assert-Equal @($result.payload.due_tracks).Count 0 "no track may be due"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "a launcher was called on NOT_DUE"
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        Assert-Equal (Get-FileSha256 $entry.Value.state_path) $before[$entry.Key] "coordinator mutated $($entry.Key) state"
    }
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_state)) "NOT_DUE created coordinator state"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_attempts)) "NOT_DUE created coordinator attempts"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_claim)) "NOT_DUE created a coordinator claim"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_mutex)) "NOT_DUE created a coordinator claim mutex"
    Assert-True (-not (Test-Path -LiteralPath $fixture.claim_archive)) "NOT_DUE created a claim archive"
}

Invoke-Test "each wake fails closed read-only when a legacy Codex automation is active" {
    $fixture = New-TestFixture
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $activeId = $legacyAutomationIds[1]
    $automationsRoot = New-LegacyAutomationFixture -Statuses @{ $activeId = "ACTIVE" }
    $trackHashes = @{}
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        $trackHashes[$entry.Key] = Get-FileSha256 $entry.Value.state_path
    }
    $automationHashes = @{}
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        $automationHashes[$id] = Get-FileSha256 $path
    }

    $result = Invoke-Coordinator -Fixture $fixture -AutomationsRoot $automationsRoot

    Assert-Equal $result.exit_code 2 "active legacy automation must block every wake: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_LEGACY_AUTOMATIONS" "active topology did not fail closed"
    Assert-Equal $result.payload.reason "LEGACY_AUTOMATION_TOPOLOGY_INVALID" "blocked wake lost its reason"
    Assert-Equal @($result.payload.legacy_automations).Count 3 "blocked wake did not inspect all legacy automations"
    $activeRecord = @($result.payload.legacy_automations | Where-Object { $_.id -eq $activeId })
    Assert-Equal $activeRecord.Count 1 "blocked wake did not report the active automation"
    Assert-Equal $activeRecord[0].status "ACTIVE" "blocked wake lost the active status"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "blocked topology allowed a launcher"
    foreach ($path in @(
        $fixture.coordinator_state,
        $fixture.coordinator_attempts,
        $fixture.coordinator_claim,
        $fixture.coordinator_mutex,
        $fixture.claim_archive
    )) {
        Assert-True (-not (Test-Path -LiteralPath $path)) "blocked topology wrote coordinator artifact: $path"
    }
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        Assert-Equal (Get-FileSha256 $entry.Value.state_path) $trackHashes[$entry.Key] "blocked topology mutated $($entry.Key) state"
    }
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        Assert-Equal (Get-FileSha256 $path) $automationHashes[$id] "topology check mutated $id"
    }
}

Invoke-Test "each all-PAUSED wake remains read-only and exposes topology evidence on NOT_DUE" {
    $fixture = New-TestFixture
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $automationsRoot = New-LegacyAutomationFixture
    $automationHashes = @{}
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        $automationHashes[$id] = Get-FileSha256 $path
    }

    $result = Invoke-Coordinator -Fixture $fixture -AutomationsRoot $automationsRoot

    Assert-Equal $result.exit_code 0 "all-PAUSED NOT_DUE wake must exit zero: $($result.raw)"
    Assert-Equal $result.payload.status "NOT_DUE" "all-PAUSED wake changed NOT_DUE semantics"
    Assert-Equal @($result.payload.legacy_automations).Count 3 "NOT_DUE did not expose all topology evidence"
    Assert-True (@($result.payload.legacy_automations | Where-Object { -not $_.verified -or $_.status -ne "PAUSED" }).Count -eq 0) "NOT_DUE accepted unverified topology"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "all-PAUSED NOT_DUE called a launcher"
    foreach ($path in @(
        $fixture.coordinator_state,
        $fixture.coordinator_attempts,
        $fixture.coordinator_claim,
        $fixture.coordinator_mutex,
        $fixture.claim_archive
    )) {
        Assert-True (-not (Test-Path -LiteralPath $path)) "all-PAUSED NOT_DUE wrote coordinator artifact: $path"
    }
    foreach ($id in $legacyAutomationIds) {
        $path = Join-Path (Join-Path $automationsRoot $id) "automation.toml"
        Assert-Equal (Get-FileSha256 $path) $automationHashes[$id] "NOT_DUE topology check mutated $id"
    }
}

foreach ($caseVariant in $legacyCaseVariants) {
    Invoke-Test "scheduled tick rejects $($caseVariant.name) without mutation or launcher call" {
        Assert-ScheduledTickRejectsLegacyCaseVariant -Field $caseVariant.field -Value $caseVariant.value
    }
}

Invoke-Test "corrupt track state is a durable retry without claim or launcher" {
    $fixture = New-TestFixture
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    [IO.File]::WriteAllText(
        $fixture.tracks.listing.state_path,
        '{corrupt-track-state',
        [Text.UTF8Encoding]::new($false)
    )
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "corrupt track state must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "corrupt track state did not retry"
    Assert-Equal $result.payload.reason "TRACK_STATE_READ_FAILED" "track-state failure reason is missing"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "corrupt track state allowed a launcher"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_claim)) "corrupt track state acquired a claim"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_mutex)) "corrupt track state acquired a claim mutex"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-Equal $records.Count 1 "track-state failure did not append exactly one terminal attempt"
    Assert-Equal $records[0].status "RETRY_NEXT_INTERVAL" "track-state terminal attempt is not retry"
    Assert-Equal $records[0].reason "TRACK_STATE_READ_FAILED" "track-state terminal attempt lost its reason"
    $state = Get-Content -Raw -LiteralPath $fixture.coordinator_state | ConvertFrom-Json
    Assert-Equal $state.status "RETRY_NEXT_INTERVAL" "track-state failure state is not retry"
    Assert-Equal $state.reason "TRACK_STATE_READ_FAILED" "track-state failure state lost its reason"
    Assert-Equal $state.last_attempt_id $records[0].attempt_id "state was published without matching ledger evidence"
}

Invoke-Test "held claim transaction mutex blocks due claim mutation and launcher" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    Write-ForeignCoordinatorClaim -Path $fixture.coordinator_claim -RunId "legitimate-owner-under-mutex" -TokenCharacter '6'
    Write-TestJson -Path $fixture.coordinator_state -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_state_v1"
        status = "RUNNING"
        coordinator_run_id = "legitimate-owner-under-mutex"
        marker = "must-remain-byte-identical"
    })
    [IO.File]::WriteAllText(
        $fixture.coordinator_attempts,
        '{"coordinator_run_id":"legitimate-owner-under-mutex","status":"RUNNING"}' + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    $claimHash = Get-FileSha256 $fixture.coordinator_claim
    $stateHash = Get-FileSha256 $fixture.coordinator_state
    $attemptsHash = Get-FileSha256 $fixture.coordinator_attempts
    $mutex = [IO.File]::Open(
        $fixture.coordinator_mutex,
        [IO.FileMode]::OpenOrCreate,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
    try {
        $result = Invoke-Coordinator -Fixture $fixture
    } finally {
        $mutex.Dispose()
    }
    Assert-Equal $result.exit_code 2 "held transaction mutex must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "held transaction mutex must retry"
    Assert-Equal $result.payload.reason "COORDINATOR_CLAIM_RECOVERY_FAILED" "mutex failure reason is wrong"
    Assert-Equal $result.payload.claim_failure_reason "claim_transaction_mutex_busy" "mutex contention classification is missing"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $claimHash "mutex loser mutated the legitimate owner's claim"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_state) $stateHash "mutex loser clobbered the legitimate owner's coordinator state"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_attempts) $attemptsHash "mutex loser appended to the legitimate owner's attempt ledger"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "mutex contention allowed a launcher"
}

Invoke-Test "claim mutex contention remains read-only when state target is blocked" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    [void](New-Item -ItemType Directory -Path $fixture.coordinator_state)
    Write-ForeignCoordinatorClaim -Path $fixture.coordinator_claim -RunId "legitimate-owner-blocked-state" -TokenCharacter '7'
    $claimHash = Get-FileSha256 $fixture.coordinator_claim
    $mutex = [IO.File]::Open(
        $fixture.coordinator_mutex,
        [IO.FileMode]::OpenOrCreate,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
    try {
        $result = Invoke-Coordinator -Fixture $fixture
    } finally {
        $mutex.Dispose()
    }
    Assert-Equal $result.exit_code 2 "claim mutex contention must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "claim mutex contention did not retry"
    Assert-Equal $result.payload.claim_failure_reason "claim_transaction_mutex_busy" "mutex contention classification is missing"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "claim mutex contention allowed a launcher"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_attempts)) "claim mutex loser wrote an unsynchronized ledger record"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_state -PathType Container) "claim mutex loser replaced the blocked state target"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $claimHash "claim mutex loser mutated the legitimate owner's claim"
}

Invoke-Test "due tracks run in fixed order and each visible worker exits before the next launcher" {
    $fixture = New-TestFixture -DueTracks @("listing", "premarket")
    $listingDone = Join-Path $fixture.root "listing.done"
    New-AlreadyExitedLauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -StatePath $fixture.tracks.listing.state_path -StateAttemptId "after-listing" -IncludeExitEvidence -ReportedExitCode 0 -CompletionMarker $listingDone
    New-AlreadyExitedLauncherStub -Path $fixture.tracks.premarket.launcher_path -TrackName "premarket" -InvocationLog $fixture.invocation_log -StatePath $fixture.tracks.premarket.state_path -StateAttemptId "after-premarket" -IncludeExitEvidence -ReportedExitCode 0 -RequiredMarker $listingDone
    New-LauncherStub -Path $fixture.tracks.preipo.launcher_path -TrackName "preipo" -InvocationLog $fixture.invocation_log
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 0 "successful due run must exit zero: $($result.raw)"
    Assert-Equal $result.payload.status "COMPLETE" "unexpected due-run status"
    Assert-Equal (@($result.payload.due_tracks) -join ",") "listing,premarket" "due order is wrong"
    $invocations = @(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track })
    Assert-Equal ($invocations -join ",") "listing,premarket" "launcher order is wrong"
    Assert-True (Test-Path -LiteralPath $listingDone) "first worker completion was not observed"
    Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_claim)) "completed coordinator claim was not released"
    Assert-True (@(Get-ChildItem -LiteralPath $fixture.claim_archive -Filter "*.completed.*.json").Count -eq 1) "completed claim was not archived"
}

Invoke-Test "already-exited worker without exact exit evidence is retry, never complete" {
    $fixture = New-TestFixture -DueTracks @("listing")
    New-AlreadyExitedLauncherStub `
        -Path $fixture.tracks.listing.launcher_path `
        -TrackName "listing" `
        -InvocationLog $fixture.invocation_log `
        -StatePath $fixture.tracks.listing.state_path `
        -StateAttemptId "fast-exit-unknown"
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }

    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "unknown fast exit must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "unknown fast exit was accepted as coordinator COMPLETE"
    Assert-Equal $result.payload.track_outcomes[0].status "WORKER_EXIT_UNKNOWN" "unknown fast exit did not fail closed"
    Assert-Equal $result.payload.track_outcomes[0].worker_wait_status "ALREADY_EXITED" "fixture did not exercise the fast-exit attach race"
    Assert-Equal $result.payload.track_outcomes[0].post_state_status "COMPLETE" "fixture did not advance the terminal track state"
}

Invoke-Test "already-exited worker with exact nonzero exit evidence fails" {
    $fixture = New-TestFixture -DueTracks @("listing")
    New-AlreadyExitedLauncherStub `
        -Path $fixture.tracks.listing.launcher_path `
        -TrackName "listing" `
        -InvocationLog $fixture.invocation_log `
        -StatePath $fixture.tracks.listing.state_path `
        -StateAttemptId "fast-exit-nonzero" `
        -IncludeExitEvidence `
        -ReportedExitCode 9
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }

    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "reported nonzero fast exit must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "reported nonzero fast exit was accepted as coordinator COMPLETE"
    Assert-Equal $result.payload.track_outcomes[0].status "WORKER_FAILED" "exact nonzero exit evidence was ignored"
    Assert-Equal $result.payload.track_outcomes[0].worker_exit_code 9 "exact nonzero exit code was not retained"
    Assert-Equal $result.payload.track_outcomes[0].worker_exit_evidence_source "LAUNCHER_REPORTED" "nonzero exit evidence source is missing"
}

Invoke-Test "already-exited worker with exact zero exit evidence may complete" {
    $fixture = New-TestFixture -DueTracks @("listing")
    New-AlreadyExitedLauncherStub `
        -Path $fixture.tracks.listing.launcher_path `
        -TrackName "listing" `
        -InvocationLog $fixture.invocation_log `
        -StatePath $fixture.tracks.listing.state_path `
        -StateAttemptId "fast-exit-zero" `
        -IncludeExitEvidence `
        -ReportedExitCode 0
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }

    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 0 "exact zero fast-exit evidence should complete: $($result.raw)"
    Assert-Equal $result.payload.status "COMPLETE" "exact zero fast-exit evidence did not preserve success"
    Assert-Equal $result.payload.track_outcomes[0].status "COMPLETE" "exact zero fast-exit track did not complete"
    Assert-Equal $result.payload.track_outcomes[0].worker_exit_code 0 "exact zero exit code was not retained"
    Assert-Equal $result.payload.track_outcomes[0].worker_exit_evidence_source "LAUNCHER_REPORTED" "zero exit evidence source is missing"
}

Invoke-Test "all attempted due tracks failing is retry, never partial" {
    $fixture = New-TestFixture -DueTracks @("listing", "premarket")
    New-StaticLauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -LauncherStatus "BROKEN"
    New-StaticLauncherStub -Path $fixture.tracks.premarket.launcher_path -TrackName "premarket" -InvocationLog $fixture.invocation_log -LauncherStatus "BROKEN"
    New-LauncherStub -Path $fixture.tracks.preipo.launcher_path -TrackName "preipo" -InvocationLog $fixture.invocation_log

    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "all-failed due tracks must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "all-failed due tracks were mislabeled partial"
    Assert-Equal @($result.payload.track_outcomes).Count 2 "all-failed fixture did not attempt both due tracks"
    Assert-True (@($result.payload.track_outcomes | Where-Object { $_.status -in @("COMPLETE", "NOT_DUE_AFTER_RECHECK") }).Count -eq 0) "all-failed fixture unexpectedly has a successful outcome"
}

Invoke-Test "one successful and one failed due track is partial retry" {
    $fixture = New-TestFixture -DueTracks @("listing", "premarket")
    New-StaticLauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -LauncherStatus "NOT_DUE"
    New-StaticLauncherStub -Path $fixture.tracks.premarket.launcher_path -TrackName "premarket" -InvocationLog $fixture.invocation_log -LauncherStatus "BROKEN"
    New-LauncherStub -Path $fixture.tracks.preipo.launcher_path -TrackName "preipo" -InvocationLog $fixture.invocation_log

    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "mixed due outcomes must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "PARTIAL_RETRY_NEXT_INTERVAL" "mixed success/failure did not remain partial retry"
    Assert-Equal @($result.payload.track_outcomes | Where-Object { $_.status -eq "NOT_DUE_AFTER_RECHECK" }).Count 1 "mixed fixture lost its successful outcome"
    Assert-Equal @($result.payload.track_outcomes | Where-Object { $_.status -notin @("COMPLETE", "NOT_DUE_AFTER_RECHECK") }).Count 1 "mixed fixture lost its failed outcome"
}

Invoke-Test "dead coordinator claim is archived before a due attempt" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = "dead-owner"
        owner_pid = 2147483647
        owner_process_started_at_utc = "2000-01-01T00:00:00Z"
        ownership_token = ("d" * 64)
        active_worker_pid = $null
        acquired_at_utc = "2000-01-01T00:00:00Z"
    })
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-stale-recovery"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.payload.status "COMPLETE" "stale recovery did not continue the due attempt"
    Assert-True (@(Get-ChildItem -LiteralPath $fixture.claim_archive -Filter "*.stale.*.json").Count -eq 1) "stale claim was not archived"
    $invocations = @(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track })
    Assert-Equal ($invocations -join ",") "listing" "stale recovery did not run the due track"
}

Invoke-Test "stale claimed RUNNING attempt is terminalized before new work" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $crashedRunId = "crashed-after-running"
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = $crashedRunId
        owner_pid = 2147483647
        owner_process_started_at_utc = "2000-01-01T00:00:00Z"
        ownership_token = ("e" * 64)
        active_worker_pid = $null
        acquired_at_utc = "2000-01-01T00:00:00Z"
    })
    $orphanRunning = [ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_attempt_v1"
        attempt_id = $crashedRunId
        coordinator_run_id = $crashedRunId
        status = "RUNNING"
        started_at_utc = "2000-01-01T00:00:00Z"
    } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText(
        $fixture.coordinator_attempts,
        $orphanRunning + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-orphan-recovery"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id

    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 0 "orphan recovery should allow new work: $($result.raw)"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    $oldRecords = @($records | Where-Object { $_.attempt_id -eq $crashedRunId })
    Assert-Equal $oldRecords.Count 2 "orphan RUNNING attempt was not terminalized exactly once"
    Assert-Equal $oldRecords[0].status "RUNNING" "orphan source record changed"
    Assert-Equal $oldRecords[1].status "RETRY_NEXT_INTERVAL" "orphan terminal is not retry"
    Assert-Equal $oldRecords[1].reason "ORPHANED_COORDINATOR_RUN_RECOVERED" "orphan terminal lost recovery reason"
    $oldTerminalIndex = [array]::IndexOf($records, $oldRecords[1])
    $newRunning = @($records | Where-Object { $_.coordinator_run_id -ne $crashedRunId -and $_.status -eq "RUNNING" })[0]
    $newRunningIndex = [array]::IndexOf($records, $newRunning)
    Assert-True ($oldTerminalIndex -lt $newRunningIndex) "new work started before orphan terminal evidence was durable"
}

Invoke-Test "stale claim substituted after inspection is preserved and returns recovery race" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = "dead-owner-before-recovery-race"
        owner_pid = 2147483647
        owner_process_started_at_utc = "2000-01-01T00:00:00Z"
        ownership_token = ("d" * 64)
        active_worker_pid = $null
        acquired_at_utc = "2000-01-01T00:00:00Z"
    })
    $replacementPath = Join-Path $fixture.root "replacement-live-claim.json"
    Write-ForeignCoordinatorClaim -Path $replacementPath -RunId "replacement-live-owner" -TokenCharacter 'a'
    $replacementHash = Get-FileSha256 $replacementPath
    Write-TestJson -Path $fixture.coordinator_state -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_state_v1"
        status = "RUNNING"
        coordinator_run_id = "replacement-live-owner"
        marker = "replacement-state"
    })
    [IO.File]::WriteAllText(
        $fixture.coordinator_attempts,
        '{"coordinator_run_id":"replacement-live-owner","status":"RUNNING"}' + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    $stateHash = Get-FileSha256 $fixture.coordinator_state
    $attemptsHash = Get-FileSha256 $fixture.coordinator_attempts

    $instrumentedCoordinator = Join-Path $fixture.root "instrumented_due_coordinator.ps1"
    $source = Get-Content -Raw -LiteralPath $coordinatorPath
    $needle = '            $archivedStaleClaim = Archive-Claim'
    $escapedReplacement = $replacementPath.Replace("'", "''")
    $injection = "            [IO.File]::Copy('$escapedReplacement', `$CoordinatorClaimPath, `$true)`r`n$needle"
    $instrumentedSource = $source.Replace($needle, $injection)
    Assert-True ($instrumentedSource -cne $source) "failed to instrument the stale inspection/archive boundary"
    $instrumentedSource | Set-Content -LiteralPath $instrumentedCoordinator -Encoding utf8NoBOM

    $result = Invoke-Coordinator -Fixture $fixture -CoordinatorScriptPath $instrumentedCoordinator
    Assert-Equal $result.exit_code 2 "stale recovery substitution must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "stale recovery substitution must retry"
    Assert-Equal $result.payload.reason "CLAIM_RECOVERY_RACE" "stale recovery substitution lost the race reason"
    Assert-Equal $result.payload.claim_failure_reason "claim_recovery_race" "underlying recovery race classification is missing"
    Assert-Equal $result.payload.pending_retry $true "stale recovery race did not preserve pending retry"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "replacement live claim was removed"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $replacementHash "replacement live claim was mutated"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "recovery race allowed a launcher"
    $archived = if (Test-Path -LiteralPath $fixture.claim_archive -PathType Container) {
        @(Get-ChildItem -LiteralPath $fixture.claim_archive -File)
    } else { @() }
    Assert-Equal $archived.Count 0 "replacement live claim was archived"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_state) $stateHash "recovery-race loser clobbered the replacement owner's state"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_attempts) $attemptsHash "recovery-race loser appended to the replacement owner's ledger"
}

Invoke-Test "stale claim archive failure is retryable nonzero and durably recorded" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = "dead-owner-archive-io-failure"
        owner_pid = 2147483647
        owner_process_started_at_utc = "2000-01-01T00:00:00Z"
        ownership_token = ("d" * 64)
        active_worker_pid = $null
        acquired_at_utc = "2000-01-01T00:00:00Z"
    })
    $claimHash = Get-FileSha256 $fixture.coordinator_claim
    [IO.File]::WriteAllText($fixture.claim_archive, "archive path blocker", [Text.UTF8Encoding]::new($false))
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "stale archive I/O failure must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "stale archive I/O failure must retry"
    Assert-Equal $result.payload.reason "COORDINATOR_CLAIM_RECOVERY_FAILED" "wrong recovery failure reason"
    Assert-Equal $result.payload.claim_failure_reason "claim_archive_race" "underlying stale archive reason was lost"
    Assert-Equal $result.payload.pending_retry $true "stale archive failure did not retain pending retry"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $claimHash "stale claim changed after failed archive"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "stale archive failure allowed a launcher"
    $state = Get-Content -Raw -LiteralPath $fixture.coordinator_state | ConvertFrom-Json
    Assert-Equal $state.status "RETRY_NEXT_INTERVAL" "durable coordinator state records false success"
    Assert-Equal $state.reason "COORDINATOR_CLAIM_RECOVERY_FAILED" "durable state lost recovery reason"
    Assert-Equal $state.pending_retry $true "durable state lost pending retry"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-Equal $records[-1].status "RETRY_NEXT_INTERVAL" "durable attempt records false success"
    Assert-Equal $records[-1].reason "COORDINATOR_CLAIM_RECOVERY_FAILED" "durable attempt lost recovery reason"
}

Invoke-Test "reused active-worker PID with mismatched start time does not suppress stale claim recovery" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $currentProcess = Get-Process -Id $PID
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = "dead-owner-reused-worker-pid"
        owner_pid = 2147483647
        owner_process_started_at_utc = "2000-01-01T00:00:00Z"
        ownership_token = ("e" * 64)
        acquired_at_utc = "2000-01-01T00:00:00Z"
        status = "WAITING_VISIBLE_WORKER"
        active_track = "listing"
        active_worker_pid = $PID
        active_worker_process_started_at_utc = $currentProcess.StartTime.ToUniversalTime().AddHours(-1).ToString("o")
    })
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-pid-reuse-recovery"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }
    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 0 "PID reuse recovery must complete: $($result.raw)"
    Assert-Equal $result.payload.status "COMPLETE" "mismatched active-worker identity suppressed the due tick"
    Assert-True (@(Get-ChildItem -LiteralPath $fixture.claim_archive -Filter "*.stale.*.json").Count -eq 1) "dead claim was not archived after PID identity mismatch"
    $invocations = @(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track })
    Assert-Equal ($invocations -join ",") "listing" "PID reuse recovery did not launch the due track"
}

Invoke-Test "active-worker exact, legacy-missing, and invalid start evidence remain fail-closed" {
    $currentProcess = Get-Process -Id $PID
    $cases = @(
        [pscustomobject]@{ name = "exact"; include_start = $true; start = $currentProcess.StartTime.ToUniversalTime().ToString("o") },
        [pscustomobject]@{ name = "legacy-missing"; include_start = $false; start = $null },
        [pscustomobject]@{ name = "invalid"; include_start = $true; start = "not-a-timestamp" }
    )
    foreach ($case in $cases) {
        $fixture = New-TestFixture -DueTracks @("listing")
        foreach ($entry in $fixture.tracks.GetEnumerator()) {
            New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
        }
        $claim = [ordered]@{
            schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
            coordinator_run_id = "active-worker-$($case.name)"
            owner_pid = 2147483647
            owner_process_started_at_utc = "2000-01-01T00:00:00Z"
            ownership_token = ("f" * 64)
            acquired_at_utc = "2000-01-01T00:00:00Z"
            status = "WAITING_VISIBLE_WORKER"
            active_track = "listing"
            active_worker_pid = $PID
        }
        if ($case.include_start) { $claim.active_worker_process_started_at_utc = $case.start }
        Write-TestJson -Path $fixture.coordinator_claim -Value $claim
        $result = Invoke-Coordinator -Fixture $fixture
        Assert-Equal $result.exit_code 0 "$($case.name) active-worker evidence must fail closed"
        Assert-Equal $result.payload.status "COORDINATOR_ALREADY_RUNNING" "$($case.name) evidence did not suppress duplicate tick: $($result.raw)"
        Assert-Equal $result.payload.reason "active_worker_alive" "$($case.name) evidence used the wrong blocking reason"
        Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "$($case.name) evidence allowed a launcher"
    }
}

Invoke-Test "corrupt coordinator claim fails closed without mutation or launcher" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    [IO.File]::WriteAllText($fixture.coordinator_claim, '{corrupt-json', [Text.UTF8Encoding]::new($false))
    $beforeHash = Get-FileSha256 $fixture.coordinator_claim
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "corrupt claim must fail closed"
    Assert-Equal $result.payload.status "BLOCKED_INVALID_COORDINATOR_CLAIM" "corrupt claim status is not blocked: $($result.raw)"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $beforeHash "corrupt claim was mutated"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "corrupt claim allowed a launcher"
    Assert-True (-not (Test-Path -LiteralPath $fixture.claim_archive)) "corrupt claim was archived as stale"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-Equal $records.Count 1 "corrupt claim did not append exactly one terminal attempt"
    Assert-Equal $records[0].status "BLOCKED_INVALID_COORDINATOR_CLAIM" "corrupt claim ledger status is not blocked"
    Assert-Equal $records[0].reason "INVALID_COORDINATOR_CLAIM" "corrupt claim ledger lost its reason"
    Assert-Equal $records[0].pending_retry $true "corrupt claim ledger did not preserve retry"
    $state = Get-Content -Raw -LiteralPath $fixture.coordinator_state | ConvertFrom-Json
    Assert-Equal $state.status "BLOCKED_INVALID_COORDINATOR_CLAIM" "corrupt claim durable state is not blocked"
    Assert-Equal $state.reason "INVALID_COORDINATOR_CLAIM" "corrupt claim durable state lost its reason"
    Assert-Equal $state.last_attempt_id $records[0].attempt_id "corrupt claim state has no matching ledger evidence"
}

Invoke-Test "schema-mismatched coordinator claim fails closed without mutation or launcher" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "unexpected_claim_schema_v99"
        coordinator_run_id = "wrong-schema"
        owner_pid = 2147483647
        active_worker_pid = $null
    })
    $beforeHash = Get-FileSha256 $fixture.coordinator_claim
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "schema mismatch must fail closed"
    Assert-Equal $result.payload.status "BLOCKED_INVALID_COORDINATOR_CLAIM" "schema mismatch status is not blocked: $($result.raw)"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $beforeHash "schema-mismatched claim was mutated"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "schema mismatch allowed a launcher"
    Assert-True (-not (Test-Path -LiteralPath $fixture.claim_archive)) "schema mismatch was archived as stale"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-Equal $records.Count 1 "schema mismatch did not append exactly one terminal attempt"
    Assert-Equal $records[0].status "BLOCKED_INVALID_COORDINATOR_CLAIM" "schema mismatch ledger status is not blocked"
    Assert-Equal $records[0].reason "INVALID_COORDINATOR_CLAIM" "schema mismatch ledger lost its reason"
    $state = Get-Content -Raw -LiteralPath $fixture.coordinator_state | ConvertFrom-Json
    Assert-Equal $state.status "BLOCKED_INVALID_COORDINATOR_CLAIM" "schema mismatch durable state is not blocked"
    Assert-Equal $state.last_attempt_id $records[0].attempt_id "schema mismatch state has no matching ledger evidence"
}

Invoke-Test "track worker_process_started_at_utc mismatch is not treated as a live reused PID" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $currentProcess = Get-Process -Id $PID
    Set-TestTrackWorkerIdentity `
        -StatePath $fixture.tracks.listing.state_path `
        -WorkerPid $PID `
        -StartField "worker_process_started_at_utc" `
        -StartedAtUtc $currentProcess.StartTime.ToUniversalTime().AddHours(-1).ToString("o")
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-track-worker-start-mismatch"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }
    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 0 "track PID reuse recovery must complete: $($result.raw)"
    Assert-Equal $result.payload.status "COMPLETE" "worker_process_started_at_utc mismatch blocked the due track"
    $invocations = @(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track })
    Assert-Equal ($invocations -join ",") "listing" "track identity mismatch did not launch the due track"
}

Invoke-Test "track last_started_at_utc is not accepted as exact PID identity" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $currentProcess = Get-Process -Id $PID
    Set-TestTrackWorkerIdentity `
        -StatePath $fixture.tracks.listing.state_path `
        -WorkerPid $PID `
        -StartField "last_started_at_utc" `
        -StartedAtUtc $currentProcess.StartTime.ToUniversalTime().AddHours(-1).ToString("o")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 0 "legacy live PID evidence must fail closed: $($result.raw)"
    Assert-Equal $result.payload.status "ACTIVE_TRACK_WORKER_PRESENT" "last_started_at_utc was incorrectly treated as exact process identity"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "legacy last_started_at_utc evidence allowed another writer"
}

Invoke-Test "track worker identity exact, legacy-missing, and invalid start evidence remain fail-closed" {
    $currentProcess = Get-Process -Id $PID
    $cases = @(
        [pscustomobject]@{ name = "exact"; field = "worker_process_started_at_utc"; start = $currentProcess.StartTime.ToUniversalTime().ToString("o") },
        [pscustomobject]@{ name = "legacy-missing"; field = ""; start = $null },
        [pscustomobject]@{ name = "invalid"; field = "worker_process_started_at_utc"; start = "not-a-timestamp" }
    )
    foreach ($case in $cases) {
        $fixture = New-TestFixture -DueTracks @("listing")
        foreach ($entry in $fixture.tracks.GetEnumerator()) {
            New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
        }
        Set-TestTrackWorkerIdentity `
            -StatePath $fixture.tracks.listing.state_path `
            -WorkerPid $PID `
            -StartField $case.field `
            -StartedAtUtc $case.start
        $result = Invoke-Coordinator -Fixture $fixture
        Assert-Equal $result.exit_code 0 "$($case.name) track worker evidence must fail closed"
        Assert-Equal $result.payload.status "ACTIVE_TRACK_WORKER_PRESENT" "$($case.name) track worker evidence did not block: $($result.raw)"
        Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "$($case.name) track worker evidence allowed a launcher"
    }
}

Invoke-Test "claim substituted before active-worker update is never mutated or archived" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $replacementClaim = Join-Path $fixture.root "foreign-active-update.claim.json"
    Write-ForeignCoordinatorClaim -Path $replacementClaim -RunId "foreign-active-update" -TokenCharacter 'a'
    $foreignHash = Get-FileSha256 $replacementClaim
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-claim-substitution"
    New-ClaimSubstitutingLauncher `
        -Path $fixture.tracks.listing.launcher_path `
        -TrackName "listing" `
        -InvocationLog $fixture.invocation_log `
        -CoordinatorClaimPath $fixture.coordinator_claim `
        -ReplacementClaimPath $replacementClaim `
        -LauncherStatus "VISIBLE_TERMINAL_LAUNCHED" `
        -WorkerPid $listingWorker.Id
    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 2 "lost ownership must use retry exit code: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "lost ownership must retry"
    Assert-Equal $result.payload.track_outcomes[0].status "CLAIM_OWNERSHIP_LOST" "active update did not report ownership loss"
    Assert-Equal $result.payload.pending_retry $true "lost ownership did not preserve pending retry"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "foreign claim was archived"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $foreignHash "foreign claim was mutated"
    Assert-True (-not (Test-Path -LiteralPath $fixture.claim_archive)) "foreign claim was moved into coordinator archive"
    $ownRecords = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.coordinator_run_id -eq $result.payload.coordinator_run_id })
    Assert-Equal @($ownRecords | Where-Object { $_.status -eq "RUNNING" }).Count 1 "ownership-loss attempt lost its RUNNING evidence"
    $terminalRecords = @($ownRecords | Where-Object { $_.status -ne "RUNNING" })
    Assert-Equal $terminalRecords.Count 1 "ownership-loss attempt was left orphan RUNNING or terminalized more than once"
    Assert-Equal $terminalRecords[0].status "RETRY_NEXT_INTERVAL" "ownership-loss terminal is not retry"
    Assert-Equal $terminalRecords[0].reason "CLAIM_OWNERSHIP_LOST" "ownership-loss terminal lost its reason"
}

Invoke-Test "claim substituted before final release is never archived" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $replacementClaim = Join-Path $fixture.root "foreign-final-release.claim.json"
    Write-ForeignCoordinatorClaim -Path $replacementClaim -RunId "foreign-final-release" -TokenCharacter 'b'
    $foreignHash = Get-FileSha256 $replacementClaim
    New-ClaimSubstitutingLauncher `
        -Path $fixture.tracks.listing.launcher_path `
        -TrackName "listing" `
        -InvocationLog $fixture.invocation_log `
        -CoordinatorClaimPath $fixture.coordinator_claim `
        -ReplacementClaimPath $replacementClaim `
        -LauncherStatus "NOT_DUE"
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "lost ownership before release must use retry exit code: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "lost ownership before release must retry"
    Assert-Equal $result.payload.reason "CLAIM_OWNERSHIP_LOST" "final release did not report ownership loss"
    Assert-Equal $result.payload.pending_retry $true "final release ownership loss did not preserve pending retry"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "foreign claim was archived during final release"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $foreignHash "foreign claim was mutated before final release"
    Assert-True (-not (Test-Path -LiteralPath $fixture.claim_archive)) "foreign claim was moved into coordinator archive"
    $ownRecords = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.coordinator_run_id -eq $result.payload.coordinator_run_id })
    Assert-Equal @($ownRecords | Where-Object { $_.status -eq "RUNNING" }).Count 1 "final-release ownership loss lost its RUNNING evidence"
    $terminalRecords = @($ownRecords | Where-Object { $_.status -ne "RUNNING" })
    Assert-Equal $terminalRecords.Count 1 "final-release ownership loss left orphan RUNNING or duplicate terminals"
    Assert-Equal $terminalRecords[0].status "RETRY_NEXT_INTERVAL" "final-release ownership-loss terminal is not retry"
    Assert-Equal $terminalRecords[0].reason "CLAIM_OWNERSHIP_LOST" "final-release ownership-loss terminal lost its reason"
}

Invoke-Test "unchanged track state after a visible worker is stale and retryable" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $listingWorker = Start-TestWorker -DelayMs 3000
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }
    $beforeHash = Get-FileSha256 $fixture.tracks.listing.state_path
    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 2 "unchanged state must use retry exit code"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "unchanged state must retry: $($result.raw)"
    Assert-Equal $result.payload.track_outcomes[0].status "STALE_TRACK_STATE" "unchanged state was accepted as complete"
    Assert-Equal (Get-FileSha256 $fixture.tracks.listing.state_path) $beforeHash "unchanged-state fixture unexpectedly advanced"
}

Invoke-Test "terminal append failure cannot leave a durable COMPLETE state" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-terminal-append-failure"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }

    $runningLedgerPath = "$($fixture.coordinator_attempts).running-only"
    $instrumentedCoordinator = Join-Path $fixture.root "instrumented_terminal_append_failure.ps1"
    $source = Get-Content -Raw -LiteralPath $coordinatorPath
    $needle = '        $persistencePhase = "terminal_attempt_append"'
    $escapedAttempts = $fixture.coordinator_attempts.Replace("'", "''")
    $escapedRunningLedger = $runningLedgerPath.Replace("'", "''")
    $injection = @"
        [IO.File]::Move('$escapedAttempts', '$escapedRunningLedger')
        [void](New-Item -ItemType Directory -Path '$escapedAttempts')
$needle
"@
    $instrumentedSource = $source.Replace($needle, $injection.TrimEnd())
    Assert-True ($instrumentedSource -cne $source) "failed to instrument terminal append failure"
    $instrumentedSource | Set-Content -LiteralPath $instrumentedCoordinator -Encoding utf8NoBOM

    $result = Invoke-Coordinator -Fixture $fixture -CoordinatorScriptPath $instrumentedCoordinator
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 2 "terminal append failure must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "terminal append failure must retry"
    Assert-Equal $result.payload.reason "COORDINATOR_PERSISTENCE_FAILED" "terminal append failure reason is missing"
    Assert-Equal $result.payload.persistence_phase "terminal_attempt_append" "terminal append failure phase is missing"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "claim was released without terminal evidence"
    $state = Get-Content -Raw -LiteralPath $fixture.coordinator_state | ConvertFrom-Json
    Assert-Equal $state.status "RETRY_NEXT_INTERVAL" "durable state records COMPLETE without terminal ledger evidence"
    Assert-Equal $state.reason "COORDINATOR_PERSISTENCE_FAILED" "durable retry state lost persistence reason"
    $runningRecords = @(Get-Content -LiteralPath $runningLedgerPath | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-Equal $runningRecords.Count 1 "failed terminal append unexpectedly produced terminal evidence"
    Assert-Equal $runningRecords[0].status "RUNNING" "pre-terminal ledger record changed"

    Remove-Item -LiteralPath $fixture.coordinator_attempts -Recurse -Force
    [IO.File]::Move($runningLedgerPath, $fixture.coordinator_attempts)
    $recoveryWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-terminal-append-recovery"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $recoveryWorker.Id
    $recovery = Invoke-Coordinator -Fixture $fixture
    try { [void]$recoveryWorker.WaitForExit(5000) } catch { }
    Assert-Equal $recovery.exit_code 0 "next tick did not recover terminal append failure: $($recovery.raw)"
    $recoveredRecords = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    $priorAttemptRecords = @($recoveredRecords | Where-Object { $_.attempt_id -eq $result.payload.coordinator_run_id })
    Assert-Equal $priorAttemptRecords.Count 2 "next tick did not add exactly one terminal for the prior RUNNING attempt"
    Assert-Equal $priorAttemptRecords[1].status "RETRY_NEXT_INTERVAL" "recovered terminal append is not retry"
    Assert-Equal $priorAttemptRecords[1].reason "ORPHANED_COORDINATOR_RUN_RECOVERED" "recovered terminal append lost its reason"
}

Invoke-Test "state write failure appends a terminal correction before retaining claim" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-state-write-failure"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }
    [void](New-Item -ItemType Directory -Path $fixture.coordinator_state)

    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 2 "state write failure must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "state write failure must retry"
    Assert-Equal $result.payload.reason "COORDINATOR_PERSISTENCE_FAILED" "state write failure reason is missing"
    Assert-Equal $result.payload.persistence_phase "coordinator_state_write" "state write failure phase is missing"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "claim was released after state persistence failure"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-True ($records.Count -ge 3) "state failure correction was not appended"
    Assert-Equal $records[-1].record_kind "TERMINAL_CORRECTION" "state failure ledger does not end in correction"
    Assert-Equal $records[-1].status "RETRY_NEXT_INTERVAL" "state failure correction retained false COMPLETE"
    Assert-Equal $records[-1].reason "COORDINATOR_PERSISTENCE_FAILED" "state failure correction lost reason"
    Assert-Equal $records[-1].corrects_attempt_id $result.payload.coordinator_run_id "state failure correction is not linked"
}

Invoke-Test "live coordinator claim suppresses a duplicate due tick" {
    $fixture = New-TestFixture -DueTracks @("listing")
    foreach ($entry in $fixture.tracks.GetEnumerator()) {
        New-LauncherStub -Path $entry.Value.launcher_path -TrackName $entry.Key -InvocationLog $fixture.invocation_log
    }
    $owner = Get-Process -Id $PID
    Write-TestJson -Path $fixture.coordinator_claim -Value ([ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
        coordinator_run_id = "live-owner"
        owner_pid = $PID
        owner_process_started_at_utc = $owner.StartTime.ToUniversalTime().ToString("o")
        ownership_token = ("c" * 64)
        active_worker_pid = $null
        acquired_at_utc = [datetimeoffset]::UtcNow.ToString("o")
    })
    $result = Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.payload.status "COORDINATOR_ALREADY_RUNNING" "duplicate tick was not suppressed: $($result.raw)"
    Assert-True (-not (Test-Path -LiteralPath $fixture.invocation_log)) "duplicate tick called a launcher"
}

Invoke-Test "worker timeout is bounded, blocks later tracks, and retains the active claim" {
    $fixture = New-TestFixture -DueTracks @("listing", "premarket")
    $timeoutWorker = Start-TestWorker -DelayMs 5000
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $timeoutWorker.Id
    New-LauncherStub -Path $fixture.tracks.premarket.launcher_path -TrackName "premarket" -InvocationLog $fixture.invocation_log
    New-LauncherStub -Path $fixture.tracks.preipo.launcher_path -TrackName "preipo" -InvocationLog $fixture.invocation_log
    $started = [Diagnostics.Stopwatch]::StartNew()
    $result = Invoke-Coordinator -Fixture $fixture -WorkerExitTimeoutSec 1
    $started.Stop()
    Assert-Equal $result.exit_code 2 "timeout must use retry exit code: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "timeout must persist retry status: $($result.raw)"
    Assert-True ($started.Elapsed.TotalSeconds -lt 4.0) "worker wait was not bounded (elapsed=$($started.Elapsed.TotalSeconds))"
    $invocations = @(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track })
    Assert-Equal ($invocations -join ",") "listing" "a later track launched while the first worker was alive"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "active worker claim was released on timeout: $($result.raw)"
    $claim = Get-Content -Raw -LiteralPath $fixture.coordinator_claim | ConvertFrom-Json
    Assert-True ([int]$claim.active_worker_pid -gt 0) "timeout claim did not retain worker PID"
    try {
        $worker = Get-Process -Id ([int]$claim.active_worker_pid) -ErrorAction Stop
        [void]$worker.WaitForExit(5000)
    } catch { }
}

foreach ($rejectionCase in @(
    @{ name="unknown status"; expected="INVALID_LAUNCHER_STATUS"; mode="unknown" },
    @{ name="nonzero launcher exit"; expected="LAUNCHER_FAILED"; mode="nonzero" },
    @{ name="invalid JSON with state PID"; expected="INVALID_LAUNCHER_OUTPUT"; mode="invalid_json" },
    @{ name="terminal_pid only"; expected="NO_VISIBLE_WORKER_PID"; mode="terminal_pid" }
    @{ name="NOT_DUE with live PID"; expected="INVALID_NOT_DUE_HANDOFF"; mode="not_due" }
)) {
    Invoke-Test "rejected handoff $($rejectionCase.name) retains a live worker and blocks another writer" {
        $fixture=New-TestFixture -DueTracks @("listing", "premarket")
        $worker=Start-TestWorker -DelayMs 8000
        try {
            New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $worker.Id
            New-StaticLauncherStub -Path $fixture.tracks.premarket.launcher_path -TrackName "premarket" -InvocationLog $fixture.invocation_log -LauncherStatus "NOT_DUE"
            $source=Get-Content -Raw -LiteralPath $fixture.tracks.listing.launcher_path
            switch ($rejectionCase.mode) {
                "unknown" { $source=$source.Replace("status = 'VISIBLE_TERMINAL_LAUNCHED'", "status = 'UNKNOWN_SUCCESS'") }
                "nonzero" { $source += "`nexit 7`n" }
                "terminal_pid" { $source=$source.Replace("visible_terminal_pid", "terminal_pid") }
                "not_due" { $source=$source.Replace("status = 'VISIBLE_TERMINAL_LAUNCHED'", "status = 'NOT_DUE'") }
                "invalid_json" {
                    $statePath=$fixture.tracks.listing.state_path.Replace("'", "''")
                    $writeState="`$state=Get-Content -Raw -LiteralPath '$statePath' | ConvertFrom-Json; `$state.worker_pid=`$workerPid; `$state | ConvertTo-Json | Set-Content -LiteralPath '$statePath' -Encoding utf8NoBOM`n"
                    $source=$source.Replace("[ordered]@{", ($writeState + "Write-Output 'unexpected launcher noise'`n[ordered]@{"))
                }
            }
            [IO.File]::WriteAllText($fixture.tracks.listing.launcher_path, $source, [Text.UTF8Encoding]::new($false))
            $result=Invoke-Coordinator -Fixture $fixture -WorkerExitTimeoutSec 1
            Assert-Equal $result.exit_code 2 "rejected live-worker handoff was accepted: $($result.raw)"
            Assert-Equal $result.payload.track_outcomes[0].status $rejectionCase.expected "wrong rejected-handoff status"
            Assert-True (-not $worker.HasExited) "live-worker fixture exited before assertions"
            Assert-Equal (@(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track }) -join ",") "listing" "another track launched while rejected worker was alive"
            Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim) "claim was released while rejected worker was alive"
            $claim=Get-Content -Raw -LiteralPath $fixture.coordinator_claim | ConvertFrom-Json
            Assert-Equal ([int]$claim.active_worker_pid) $worker.Id "claim did not preserve exact live worker PID"
            $claimHash=Get-FileSha256 $fixture.coordinator_claim
            $again=Invoke-Coordinator -Fixture $fixture -WorkerExitTimeoutSec 1
            Assert-Equal $again.payload.status "COORDINATOR_ALREADY_RUNNING" "next tick did not suppress duplicate for rejected live worker"
            Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $claimHash "duplicate tick changed retained claim"
            Assert-Equal (@(Get-Content -LiteralPath $fixture.invocation_log | ForEach-Object { ($_ | ConvertFrom-Json).track }) -join ",") "listing" "duplicate tick launched a writer"
        } finally {
            [void]$worker.WaitForExit(10000)
            $worker.Dispose()
        }
    }
}

Invoke-Test "rejected handoff without observable PID preserves explicit unresolved identity" {
    $fixture=New-TestFixture -DueTracks @("listing", "premarket")
    $oldState=Get-Content -Raw -LiteralPath $fixture.tracks.listing.state_path | ConvertFrom-Json
    $oldState.status="COMPLETE"
    Write-TestJson -Path $fixture.tracks.listing.state_path -Value $oldState
    $logPath=$fixture.invocation_log.Replace("'", "''")
    $launcherText="param([switch]`$ScheduledTick,[switch]`$Json)`n[IO.File]::AppendAllText('$logPath', '{`"track`":`"listing`"}' + [Environment]::NewLine)`nWrite-Output 'malformed handoff without PID'`n"
    [IO.File]::WriteAllText($fixture.tracks.listing.launcher_path, $launcherText, [Text.UTF8Encoding]::new($false))
    New-StaticLauncherStub -Path $fixture.tracks.premarket.launcher_path -TrackName "premarket" -InvocationLog $fixture.invocation_log -LauncherStatus "NOT_DUE"
    $result=Invoke-Coordinator -Fixture $fixture
    Assert-Equal $result.exit_code 2 "unknown handoff did not fail"
    Assert-Equal $result.payload.track_outcomes[0].worker_wait_status "REJECTED_HANDOFF_IDENTITY_UNRESOLVED" "missing PID was treated as proof of exit"
    Assert-Equal (@(Get-Content -LiteralPath $fixture.invocation_log).Count) 1 "unknown handoff did not block later tracks"
    $claim=Get-Content -Raw -LiteralPath $fixture.coordinator_claim | ConvertFrom-Json
    Assert-Equal $claim.status "REJECTED_HANDOFF_IDENTITY_UNRESOLVED" "unresolved identity was not durable"
    Assert-Equal $claim.active_worker_pid $null "a worker PID was invented"
    $claimHash=Get-FileSha256 $fixture.coordinator_claim
    $next=Invoke-Coordinator -Fixture $fixture
    Assert-Equal $next.exit_code 2 "unresolved handoff allowed a duplicate"
    Assert-Equal $next.payload.claim_failure_reason "worker_identity_unresolved" "unresolved identity reason was lost"
    Assert-Equal (Get-FileSha256 $fixture.coordinator_claim) $claimHash "unresolved claim was modified or archived"
    Assert-Equal (@(Get-Content -LiteralPath $fixture.invocation_log).Count) 1 "next tick launched after an unresolved handoff"
}

Invoke-Test "unresolved handoff recovers only from fresh canonical PID and exact start evidence" {
    $fixture=New-TestFixture -DueTracks @("listing")
    [IO.File]::WriteAllText($fixture.tracks.listing.launcher_path, "param([switch]`$ScheduledTick,[switch]`$Json)`nWrite-Output 'invalid handoff'`n", [Text.UTF8Encoding]::new($false))
    $first=Invoke-Coordinator -Fixture $fixture
    Assert-Equal $first.payload.track_outcomes[0].worker_wait_status "REJECTED_HANDOFF_IDENTITY_UNRESOLVED" "first handoff was not unresolved"
    $originalClaim=Get-Content -Raw -LiteralPath $fixture.coordinator_claim | ConvertFrom-Json
    $worker=Start-TestWorker -DelayMs 8000 -StatePath $fixture.tracks.listing.state_path -AttemptId "late-terminal"
    try {
        $state=Get-Content -Raw -LiteralPath $fixture.tracks.listing.state_path | ConvertFrom-Json
        $state.status="RUNNING"
        $state.last_attempt_id="late-start"
        $state.worker_pid=$worker.Id
        $state | Add-Member -NotePropertyName worker_process_started_at_utc -NotePropertyValue $worker.StartTime.ToUniversalTime().ToString("o") -Force
        Write-TestJson -Path $fixture.tracks.listing.state_path -Value $state
        $next=Invoke-Coordinator -Fixture $fixture
        Assert-Equal $next.payload.status "COORDINATOR_ALREADY_RUNNING" "fresh exact canonical worker was not recovered"
        Assert-Equal $next.payload.reason "active_worker_alive" "recovered worker did not suppress duplicate"
        $recovered=Get-Content -Raw -LiteralPath $fixture.coordinator_claim | ConvertFrom-Json
        Assert-Equal ([int]$recovered.active_worker_pid) $worker.Id "claim did not bind recovered worker identity"
        Assert-Equal $recovered.coordinator_run_id $originalClaim.coordinator_run_id "recovery replaced the unresolved owner"
        [void]$worker.WaitForExit(10000)
        New-StaticLauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -LauncherStatus "NOT_DUE"
        $afterExit=Invoke-Coordinator -Fixture $fixture
        Assert-Equal $afterExit.exit_code 0 "verified worker exit did not unblock later tick: $($afterExit.raw)"
        Assert-True (-not (Test-Path -LiteralPath $fixture.coordinator_claim)) "completed recovery claim stayed permanently blocked"
        $archives=@(Get-ChildItem -LiteralPath $fixture.claim_archive -File | ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json })
        Assert-True (@($archives | Where-Object { $_.coordinator_run_id -eq $originalClaim.coordinator_run_id }).Count -eq 1) "original rejected claim was not preserved in archive"
    } finally {
        [void]$worker.WaitForExit(10000)
        $worker.Dispose()
    }
}

Invoke-Test "claim release archive failure corrects durable terminal state and ledger" {
    $fixture = New-TestFixture -DueTracks @("listing")
    $listingWorker = Start-TestWorker -DelayMs 3000 -StatePath $fixture.tracks.listing.state_path -AttemptId "after-release-failure"
    New-LauncherStub -Path $fixture.tracks.listing.launcher_path -TrackName "listing" -InvocationLog $fixture.invocation_log -WorkerPidOverride $listingWorker.Id
    foreach ($track in @("premarket", "preipo")) {
        New-LauncherStub -Path $fixture.tracks[$track].launcher_path -TrackName $track -InvocationLog $fixture.invocation_log
    }
    [IO.File]::WriteAllText($fixture.claim_archive, "archive path blocker", [Text.UTF8Encoding]::new($false))
    $result = Invoke-Coordinator -Fixture $fixture
    try { [void]$listingWorker.WaitForExit(5000) } catch { }
    Assert-Equal $result.exit_code 2 "claim release failure must be nonzero: $($result.raw)"
    Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "claim release failure must retry"
    Assert-Equal $result.payload.reason "COORDINATOR_CLAIM_RELEASE_FAILED" "claim release failure reason is missing"
    Assert-Equal $result.payload.pending_retry $true "claim release failure did not preserve pending retry"
    Assert-True (Test-Path -LiteralPath $fixture.coordinator_claim -PathType Leaf) "owned claim was lost after failed release"
    $state = Get-Content -Raw -LiteralPath $fixture.coordinator_state | ConvertFrom-Json
    Assert-Equal $state.status "RETRY_NEXT_INTERVAL" "durable coordinator state retained false COMPLETE"
    Assert-Equal $state.reason "COORDINATOR_CLAIM_RELEASE_FAILED" "durable state lost release failure reason"
    Assert-Equal $state.pending_retry $true "durable state lost pending retry"
    $records = @(Get-Content -LiteralPath $fixture.coordinator_attempts | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-True ($records.Count -ge 3) "release failure correction was not appended"
    $correction = $records[-1]
    Assert-Equal $correction.status "RETRY_NEXT_INTERVAL" "final ledger record retained false COMPLETE"
    Assert-Equal $correction.record_kind "TERMINAL_CORRECTION" "final ledger record is not a correction"
    Assert-Equal $correction.corrects_attempt_id $result.payload.coordinator_run_id "correction is not linked to the terminal attempt"
    Assert-Equal $correction.reason "COORDINATOR_CLAIM_RELEASE_FAILED" "correction lost release reason"
    Assert-Equal $correction.pending_retry $true "correction lost pending retry"
}

Invoke-Test "installer defines one hidden five-minute no-model task and uninstaller is non-destructive" {
    $installer = Get-Content -Raw -LiteralPath $installerPath
    $uninstaller = Get-Content -Raw -LiteralPath $uninstallerPath
    Assert-True ($installer -match "Register-ScheduledTask") "installer does not register a Scheduled Task"
    Assert-True ($installer -match "FromMinutes\(5\)") "installer does not use a five-minute trigger"
    Assert-True ($installer -match '"-WindowStyle"\s*,\s*"Hidden"|WindowStyle Hidden') "scheduled coordinator process is not hidden"
    Assert-True ($installer -match "invoke_listing_strategy_due_coordinator\.ps1") "task does not run the coordinator"
    Assert-True ($installer -notmatch "canonical_strategy_runtime\.staging\.json") "installer still defaults to the in-repo staging registry"
    Assert-True ($installer -match 'Parameter\(Mandatory\s*=\s*\$true\)') "installer does not require explicit production bindings"
    Assert-True ($installer -match "ExpectedRegistrySha256") "installer does not bind the raw registry SHA"
    Assert-True ($installer -match "ExpectedInstallerSha256") "installer does not bind its own SHA"
    Assert-True ($installer -match "ExpectedCoordinatorSha256") "installer does not bind the coordinator SHA"
    Assert-True ($installer -match "ExpectedValidatorSha256") "installer does not bind the validator SHA"
    Assert-True ($installer -match "ExpectedReceiptSha256") "installer does not bind the receipt SHA"
    Assert-True ($installer -match "ExpectedControlPlaneGitCommit") "installer does not bind the control-plane commit"
    Assert-True ($installer -notmatch '\[string\]\$CoordinatorPath') "installer accepts a production coordinator override"
    Assert-True ($installer -match "GetFinalPathNameByHandle") "installer does not resolve reparse targets physically"
    Assert-True ($installer -match "DryRun") "installer has no dry-run gate"
    Assert-True ($installer -notmatch "start_(listing_momentum|premarket|preipo)") "task directly launches a track orchestrator"
    Assert-True ($uninstaller -match "Unregister-ScheduledTask") "uninstaller does not unregister the task"
    Assert-True ($uninstaller -notmatch "Remove-Item") "uninstaller must not delete state, attempts, claims, or manifests"
    $coordinator = Get-Content -Raw -LiteralPath $coordinatorPath
    Assert-True ($coordinator -match "ExpectedValidatorSha256") "coordinator does not bind the validator SHA"
    Assert-True ($coordinator -match "ExpectedReceiptSha256") "coordinator does not bind the receipt SHA"
    Assert-True ($coordinator -match "ExpectedControlPlaneGitCommit") "coordinator does not bind the control-plane commit"
    Assert-True ($coordinator -match "GetFinalPathNameByHandle") "coordinator does not resolve reparse targets physically"
    Assert-True ($coordinator -match 'cat-file",\s*"blob"') "coordinator does not bind control-plane files to exact committed blobs"
    Assert-True ($coordinator -match 'canonical_strategy_runtime\.json') "coordinator does not require the immutable registry filename"
    Assert-True ($coordinator -match 'materialization_receipt\.json') "coordinator does not require the immutable receipt filename"
    Assert-True ($coordinator -match 'zolotyaylopata\.external_registry_materialization_receipt\.v2') "coordinator does not validate the receipt schema"
    Assert-True ($coordinator -match 'PUBLICATION_INSIDE_CANONICAL_REPOSITORY') "coordinator does not reject in-repository publications"
    Assert-True ($coordinator -match 'CONTROL_PLANE_FILE_SHA256_MISMATCH') "coordinator does not require worktree and committed-blob SHA equality"
    Assert-True ($coordinator -match 'CANONICAL_REGISTRY_NOT_EXACT_BOUND_PUBLICATION') "coordinator does not require the exact bound validator result"
    Assert-True ($coordinator -match '\$expectedDecision = if \(\$isActivePublication\) \{ "ACTIVE_ROUTABLE" \} else \{ "STAGED_FAIL_CLOSED" \}') "coordinator does not distinguish exact ACTIVE and STAGING results"
    Assert-True ($coordinator -notmatch '-cin\s+@\("STAGED_FAIL_CLOSED",\s*"PARTIAL_RUNTIME_BLOCK"\)') "coordinator still promotes PARTIAL_RUNTIME_BLOCK"
    Assert-True ($coordinator -notmatch "WindowStyle\s+Hidden") "coordinator hides a worker"
    Assert-True ($coordinator -notmatch "Start-Process") "coordinator starts a process outside the existing visible orchestrators"
}

Invoke-Test "installer rejects its own worktree after committed hash binding" {
    $root = New-LegacyAutomationFixture
    $result = Invoke-InstallerDryRun -AutomationsRoot $root -TamperInstallerAfterHash
    Assert-Equal $result.exit_code 2 "tampered installer was accepted: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_INSTALL_BINDING" "tampered installer rejection status is ambiguous"
    Assert-True ([string]$result.payload.reason -match "INSTALLER_SHA256_MISMATCH|INSTALLER_WORKTREE_DIFFERS_FROM_COMMIT") "tampered installer did not fail its self-binding"
    Assert-Equal $result.payload.registration_attempted $false "tampered installer rejection attempted registration"
}

Invoke-Test "installer blocks when any legacy Codex automation is active" {
    $activeId = $legacyAutomationIds[1]
    $root = New-LegacyAutomationFixture -Statuses @{ $activeId = "ACTIVE" }
    $result = Invoke-InstallerDryRun -AutomationsRoot $root
    Assert-Equal $result.exit_code 2 "ACTIVE legacy automation must block installation"
    Assert-Equal $result.payload.status "BLOCKED_LEGACY_AUTOMATIONS" "ACTIVE topology did not fail closed: $($result.raw)"
    $activeRecord = @($result.payload.legacy_automations | Where-Object { $_.id -eq $activeId })
    Assert-Equal $activeRecord.Count 1 "blocked output does not expose the active automation"
    Assert-Equal $activeRecord[0].status "ACTIVE" "blocked output lost the active status"
    Assert-Equal $result.payload.registration_attempted $false "blocked dry-run attempted Scheduled Task registration"
}

Invoke-Test "installer rejects a physical publication junction before coordinator preflight" {
    $root = New-LegacyAutomationFixture
    $result = Invoke-InstallerDryRun -AutomationsRoot $root -UsePublicationJunction
    Assert-Equal $result.exit_code 2 "publication junction was accepted: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_INSTALL_BINDING" "junction rejection status is ambiguous"
    Assert-True ([string]$result.payload.reason -match "REGISTRY_PATH_REPARSE_ALIAS") "junction rejection did not expose the physical alias"
    Assert-Equal $result.payload.registration_attempted $false "junction rejection attempted registration"
}

Invoke-Test "installer rejects PARTIAL runtime evidence even when receipt claims staging" {
    $root = New-LegacyAutomationFixture
    $result = Invoke-InstallerDryRun -AutomationsRoot $root -CorruptRuntimeBinding
    Assert-Equal $result.exit_code 2 "PARTIAL runtime evidence was accepted: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_COORDINATOR_PREFLIGHT" "PARTIAL runtime did not fail at coordinator preflight"
    Assert-Equal $result.payload.registration_attempted $false "PARTIAL runtime rejection attempted registration"
}

Invoke-Test "installer rejects receipt bytes changed after hash binding" {
    $root = New-LegacyAutomationFixture
    $result = Invoke-InstallerDryRun -AutomationsRoot $root -TamperReceiptAfterHash
    Assert-Equal $result.exit_code 2 "tampered receipt was accepted: $($result.raw)"
    Assert-Equal $result.payload.status "BLOCKED_INSTALL_BINDING" "tampered receipt rejection status is ambiguous"
    Assert-True ([string]$result.payload.reason -match "RECEIPT_SHA256_MISMATCH") "tampered receipt did not fail on its raw hash"
    Assert-Equal $result.payload.registration_attempted $false "tampered receipt rejection attempted registration"
}

foreach ($caseVariant in $legacyCaseVariants) {
    Invoke-Test "installer dry-run rejects $($caseVariant.name) without mutation or registration" {
        Assert-InstallerRejectsLegacyCaseVariant -Field $caseVariant.field -Value $caseVariant.value
    }
}

Invoke-Test "installer dry-run succeeds only when all three legacy automations are paused" {
    $root = New-LegacyAutomationFixture
    $result = Invoke-InstallerDryRun -AutomationsRoot $root
    Assert-Equal $result.exit_code 0 "all-PAUSED dry-run must exit zero: $($result.raw)"
    Assert-Equal $result.payload.status "STAGED_FAIL_CLOSED" "all-PAUSED dry-run is not fail-closed"
    Assert-Equal $result.payload.reason "NOT_ACTIVATED" "all-PAUSED dry-run has ambiguous activation status"
    Assert-Equal @($result.payload.legacy_automations).Count 3 "dry-run did not verify all three legacy automations"
    Assert-Equal ((@($result.payload.legacy_automations | ForEach-Object { $_.id }) | Sort-Object) -join ",") (($legacyAutomationIds | Sort-Object) -join ",") "dry-run returned the wrong automation ids"
    Assert-True (@($result.payload.legacy_automations | Where-Object { $_.status -ne "PAUSED" }).Count -eq 0) "dry-run accepted a non-PAUSED status"
    $actionArguments = [string]$result.payload.action_arguments
    $expectedRegistryPath = [IO.Path]::GetFullPath($result.registry_path)
    $expectedRegistrySha = $result.registry_sha256
    $expectedCoordinatorSha = $result.coordinator_sha256
    $expectedReceiptPath = [IO.Path]::GetFullPath($result.receipt_path)
    $expectedReceiptSha = $result.receipt_sha256
    $expectedValidatorSha = $result.validator_sha256
    $expectedControlPlaneCommit = $result.control_plane_commit
    Assert-True ($actionArguments -match '(?:^|\s)-ScheduledTick(?:\s|$)') "scheduled task action does not require ScheduledTick"
    Assert-True ($actionArguments -match ('(?:^|\s)-RegistryPath\s+"' + [regex]::Escape($expectedRegistryPath) + '"(?:\s|$)')) "scheduled task action does not bind the exact registry path"
    Assert-True ($actionArguments -match ('(?:^|\s)-ExpectedRegistrySha256\s+' + $expectedRegistrySha + '(?:\s|$)')) "scheduled task action does not bind the exact registry SHA"
    Assert-True ($actionArguments -match ('(?:^|\s)-ExpectedCoordinatorSha256\s+' + $expectedCoordinatorSha + '(?:\s|$)')) "scheduled task action does not bind the exact coordinator SHA"
    Assert-True ($actionArguments -match ('(?:^|\s)-ReceiptPath\s+"' + [regex]::Escape($expectedReceiptPath) + '"(?:\s|$)')) "scheduled task action does not bind the exact receipt path"
    Assert-True ($actionArguments -match ('(?:^|\s)-ExpectedReceiptSha256\s+' + $expectedReceiptSha + '(?:\s|$)')) "scheduled task action does not bind the exact receipt SHA"
    Assert-True ($actionArguments -match ('(?:^|\s)-ExpectedValidatorSha256\s+' + $expectedValidatorSha + '(?:\s|$)')) "scheduled task action does not bind the exact validator SHA"
    Assert-True ($actionArguments -match ('(?:^|\s)-ExpectedControlPlaneGitCommit\s+' + $expectedControlPlaneCommit + '(?:\s|$)')) "scheduled task action does not bind the exact control-plane commit"
    foreach ($forbidden in @(
        "CodexAutomationsRoot",
        "ListingStatePath",
        "PremarketStatePath",
        "PreipoStatePath",
        "ListingLauncherPath",
        "PremarketLauncherPath",
        "PreipoLauncherPath",
        "CoordinatorStatePath",
        "CoordinatorAttemptsPath",
        "CoordinatorClaimPath"
    )) {
        Assert-True ($actionArguments -notmatch ('(?:^|\s)-' + $forbidden + '(?:\s|$)')) "scheduled task action contains forbidden production override -$forbidden"
    }
    Assert-Equal $result.payload.registry_path $expectedRegistryPath "dry-run exposes the wrong registry path"
    Assert-Equal $result.payload.expected_registry_sha256 $expectedRegistrySha "dry-run exposes the wrong registry SHA"
    Assert-Equal $result.payload.expected_coordinator_sha256 $expectedCoordinatorSha "dry-run exposes the wrong coordinator SHA"
    Assert-Equal $result.payload.receipt_path $expectedReceiptPath "dry-run exposes the wrong receipt path"
    Assert-Equal $result.payload.expected_receipt_sha256 $expectedReceiptSha "dry-run exposes the wrong receipt SHA"
    Assert-Equal $result.payload.expected_validator_sha256 $expectedValidatorSha "dry-run exposes the wrong validator SHA"
    Assert-Equal $result.payload.expected_control_plane_git_commit $expectedControlPlaneCommit "dry-run exposes the wrong control-plane commit"
    Assert-Equal $result.payload.coordinator_preflight.status "STAGED_FAIL_CLOSED" "dry-run did not execute the read-only staging preflight"
    Assert-Equal $result.payload.coordinator_preflight.reason "NOT_ACTIVATED" "dry-run staging preflight reason is ambiguous"
    Assert-Equal $result.payload.coordinator_preflight.execution_performed $false "dry-run coordinator preflight performed execution"
    Assert-Equal $result.payload.coordinator_preflight.launch_allowed $false "dry-run coordinator preflight allowed launch"
    Assert-Equal $result.payload.registration_attempted $false "dry-run attempted Scheduled Task registration"
}

foreach ($root in $script:testRoots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $resolvedRoot = [System.IO.Path]::GetFullPath($root)
    $resolvedTools = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $leaf = Split-Path -Leaf $resolvedRoot
    if (-not $resolvedRoot.StartsWith($resolvedTools, [StringComparison]::OrdinalIgnoreCase) -or -not $leaf.StartsWith(".test_listing_strategy_due_coordinator_")) {
        throw "refusing to remove unexpected test directory: $resolvedRoot"
    }
    Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
}

foreach ($root in $script:externalTestRoots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $resolvedRoot = [System.IO.Path]::GetFullPath($root)
    $resolvedTemp = [System.IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $leaf = Split-Path -Leaf $resolvedRoot
    if (-not $resolvedRoot.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or -not $leaf.StartsWith("listing-coordinator-installer-")) {
        throw "refusing to remove unexpected external test directory: $resolvedRoot"
    }
    Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
}

Write-Host "RESULT passed=$script:passed failed=$script:failed"
if ($script:failed -gt 0 -or $script:passed -eq 0) { exit 1 }
exit 0
