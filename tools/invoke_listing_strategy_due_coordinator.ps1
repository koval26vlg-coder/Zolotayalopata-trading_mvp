param(
    [switch]$ScheduledTick,
    [switch]$Json,
    [string]$NowUtc = "",
    [ValidateRange(1, 86400)][int]$WorkerExitTimeoutSec = 1800,
    [string]$ListingStatePath = "",
    [string]$PremarketStatePath = "",
    [string]$PreipoStatePath = "",
    [string]$ListingLauncherPath = "",
    [string]$PremarketLauncherPath = "",
    [string]$PreipoLauncherPath = "",
    [string]$CoordinatorStatePath = "",
    [string]$CoordinatorAttemptsPath = "",
    [string]$CoordinatorClaimPath = "",
    [string]$CoordinatorClaimArchivePath = "",
    [string]$CoordinatorClaimMutexPath = "",
    [string]$CodexAutomationsRoot = ""
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

if (-not $ScheduledTick) {
    [ordered]@{
        schema = "trading_mvp_listing_strategy_due_coordinator_state_v1"
        status = "NO_EXECUTION"
        reason = "SCHEDULED_TICK_REQUIRED"
        execution_performed = $false
    } | ConvertTo-Json -Depth 10
    exit 2
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runGateDir = Join-Path $repoRoot "docs\agent-log\run-gates"
if (-not $ListingStatePath) { $ListingStatePath = Join-Path $runGateDir "listing_momentum_forward_automation_state.json" }
if (-not $PremarketStatePath) { $PremarketStatePath = Join-Path $runGateDir "premarket_perp_listing_automation_state.json" }
if (-not $PreipoStatePath) { $PreipoStatePath = Join-Path $runGateDir "preipo_perpetual_event_automation_state.json" }
if (-not $ListingLauncherPath) { $ListingLauncherPath = Join-Path $PSScriptRoot "start_listing_momentum_forward_automation_visible.ps1" }
if (-not $PremarketLauncherPath) { $PremarketLauncherPath = Join-Path $PSScriptRoot "start_premarket_perp_listing_automation_visible.ps1" }
if (-not $PreipoLauncherPath) { $PreipoLauncherPath = Join-Path $PSScriptRoot "start_preipo_perpetual_event_automation_visible.ps1" }
if (-not $CoordinatorStatePath) { $CoordinatorStatePath = Join-Path $runGateDir "listing_strategy_due_coordinator_state.json" }
if (-not $CoordinatorAttemptsPath) { $CoordinatorAttemptsPath = Join-Path $runGateDir "listing_strategy_due_coordinator_attempts.jsonl" }
if (-not $CoordinatorClaimPath) { $CoordinatorClaimPath = Join-Path $runGateDir "listing_strategy_due_coordinator.claim.json" }
if (-not $CoordinatorClaimArchivePath) { $CoordinatorClaimArchivePath = Join-Path $runGateDir "listing_strategy_due_coordinator_claim_archive" }
if (-not $CoordinatorClaimMutexPath) { $CoordinatorClaimMutexPath = "$CoordinatorClaimPath.mutex" }
if (-not $CodexAutomationsRoot) {
    $userProfilePath = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if (-not $userProfilePath) { throw "Windows user profile path is unavailable" }
    $CodexAutomationsRoot = Join-Path $userProfilePath ".codex\automations"
}

$ListingStatePath = [IO.Path]::GetFullPath($ListingStatePath)
$PremarketStatePath = [IO.Path]::GetFullPath($PremarketStatePath)
$PreipoStatePath = [IO.Path]::GetFullPath($PreipoStatePath)
$ListingLauncherPath = [IO.Path]::GetFullPath($ListingLauncherPath)
$PremarketLauncherPath = [IO.Path]::GetFullPath($PremarketLauncherPath)
$PreipoLauncherPath = [IO.Path]::GetFullPath($PreipoLauncherPath)
$CoordinatorStatePath = [IO.Path]::GetFullPath($CoordinatorStatePath)
$CoordinatorAttemptsPath = [IO.Path]::GetFullPath($CoordinatorAttemptsPath)
$CoordinatorClaimPath = [IO.Path]::GetFullPath($CoordinatorClaimPath)
$CoordinatorClaimArchivePath = [IO.Path]::GetFullPath($CoordinatorClaimArchivePath)
$CoordinatorClaimMutexPath = [IO.Path]::GetFullPath($CoordinatorClaimMutexPath)
$CodexAutomationsRoot = [IO.Path]::GetFullPath($CodexAutomationsRoot)

$coordinatorSchema = "trading_mvp_listing_strategy_due_coordinator_state_v1"
$attemptSchema = "trading_mvp_listing_strategy_due_coordinator_attempt_v1"
$claimSchema = "trading_mvp_listing_strategy_due_coordinator_claim_v1"
$legacyAutomationIds = @(
    "zolotyaylopata-listing-momentum-monitor",
    "zolotyaylopata-pre-market-perpetual-listing-impulse-monitor",
    "zolotyaylopata-pre-ipo-perpetual-event-monitor"
)
$trackOrder = @("listing", "premarket", "preipo")
$trackDefinitions = [ordered]@{
    listing = [ordered]@{ state_path = $ListingStatePath; launcher_path = $ListingLauncherPath }
    premarket = [ordered]@{ state_path = $PremarketStatePath; launcher_path = $PremarketLauncherPath }
    preipo = [ordered]@{ state_path = $PreipoStatePath; launcher_path = $PreipoLauncherPath }
}

function Get-UtcIso {
    param([datetimeoffset]$Value = [datetimeoffset]::UtcNow)
    return $Value.ToUniversalTime().ToString("o")
}

function Resolve-NowUtc {
    if (-not $NowUtc) { return [datetimeoffset]::UtcNow }
    $parsed = [datetimeoffset]::MinValue
    if (-not [datetimeoffset]::TryParse(
        $NowUtc,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$parsed
    )) {
        throw "invalid NowUtc: $NowUtc"
    }
    return $parsed.ToUniversalTime()
}

function Ensure-ParentDirectory {
    param([string]$Path)
    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}

function ConvertTo-JsonBytes {
    param($Value)
    $text = $Value | ConvertTo-Json -Depth 40
    return [Text.UTF8Encoding]::new($false).GetBytes($text)
}

function Write-JsonAtomic {
    param([string]$Path, $Value)
    Ensure-ParentDirectory -Path $Path
    $temporaryPath = "$Path.tmp.$PID.$([guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllBytes($temporaryPath, (ConvertTo-JsonBytes -Value $Value))
        [IO.File]::Move($temporaryPath, $Path, $true)
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Append-Attempt {
    param($Value)
    Ensure-ParentDirectory -Path $CoordinatorAttemptsPath
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(
        (($Value | ConvertTo-Json -Compress -Depth 40) + [Environment]::NewLine)
    )
    $stream = [IO.FileStream]::new(
        $CoordinatorAttemptsPath,
        [IO.FileMode]::Append,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read,
        4096,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Enter-CoordinatorClaimMutex {
    Ensure-ParentDirectory -Path $CoordinatorClaimMutexPath
    try {
        return [IO.FileStream]::new(
            $CoordinatorClaimMutexPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None,
            1,
            [IO.FileOptions]::WriteThrough
        )
    } catch {
        throw "CLAIM_TRANSACTION_MUTEX_BUSY: $($_.Exception.Message)"
    }
}

function Get-Sha256 {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [Convert]::ToHexString($sha.ComputeHash($Bytes)).ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Read-LegacyAutomationTopology {
    $records = [System.Collections.Generic.List[object]]::new()
    $validationErrors = [System.Collections.Generic.List[string]]::new()
    $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
    foreach ($automationId in $legacyAutomationIds) {
        $automationPath = Join-Path (Join-Path $CodexAutomationsRoot $automationId) "automation.toml"
        $record = [ordered]@{
            id = $automationId
            path = $automationPath
            status = $null
            config_sha256 = $null
            verified = $false
            error = $null
        }
        if (-not (Test-Path -LiteralPath $automationPath -PathType Leaf)) {
            $record.error = "automation.toml is missing"
            $validationErrors.Add("$automationId`: automation.toml is missing")
            $records.Add([pscustomobject]$record)
            continue
        }
        try {
            $bytes = [IO.File]::ReadAllBytes($automationPath)
            $text = $strictUtf8.GetString($bytes)
            $record.config_sha256 = Get-Sha256 -Bytes $bytes
            $idMatches = [regex]::Matches($text, '(?m)^\s*id\s*=\s*"([^"]+)"\s*$')
            $statusMatches = [regex]::Matches($text, '(?m)^\s*status\s*=\s*"([^"]+)"\s*$')
            if ($idMatches.Count -ne 1) { throw "expected exactly one id field" }
            if ($statusMatches.Count -ne 1) { throw "expected exactly one status field" }
            $parsedId = $idMatches[0].Groups[1].Value
            $record.status = $statusMatches[0].Groups[1].Value
            if ($parsedId -cne $automationId) { throw "id mismatch: got '$parsedId'" }
            if ($record.status -cne "PAUSED") { throw "status must be PAUSED, got '$($record.status)'" }
            $record.verified = $true
        } catch {
            $record.error = $_.Exception.Message
            $validationErrors.Add("$automationId`: $($_.Exception.Message)")
        }
        $records.Add([pscustomobject]$record)
    }
    return [pscustomobject]@{
        valid = ($validationErrors.Count -eq 0)
        automations = @($records)
        validation_errors = @($validationErrors)
    }
}

function Read-TrackState {
    param(
        [string]$Track,
        [string]$Path,
        [datetimeoffset]$ReferenceUtc
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Track state file not found: $Path"
    }
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { throw "$Track state file is empty: $Path" }
    $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
    try {
        $state = $text | ConvertFrom-Json -DateKind String -ErrorAction Stop
    } catch {
        throw "$Track state JSON is invalid: $($_.Exception.Message)"
    }
    $nextProperty = $state.PSObject.Properties["next_interval_at_utc"]
    if (-not $nextProperty -or -not [string]$nextProperty.Value) {
        throw "$Track state lacks next_interval_at_utc: $Path"
    }
    $next = [datetimeoffset]::MinValue
    if (-not [datetimeoffset]::TryParse(
        [string]$nextProperty.Value,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$next
    )) {
        throw "$Track state has invalid next_interval_at_utc: $Path"
    }
    $workerPid = $null
    $workerProperty = $state.PSObject.Properties["worker_pid"]
    if ($workerProperty -and $workerProperty.Value) {
        try { $workerPid = [int]$workerProperty.Value } catch { $workerPid = $null }
    }
    $workerProcessStartedAtUtc = $null
    $workerProcessStartedAtSource = $null
    if ($workerPid) {
        $startProperty = $state.PSObject.Properties["worker_process_started_at_utc"]
        if ($startProperty -and [string]$startProperty.Value) {
            $workerProcessStartedAtUtc = [string]$startProperty.Value
            $workerProcessStartedAtSource = "worker_process_started_at_utc"
        }
    }
    return [pscustomobject]@{
        track = $Track
        path = $Path
        state = $state
        state_sha256 = Get-Sha256 -Bytes $bytes
        next_interval_at_utc = $next.ToUniversalTime()
        due = ($ReferenceUtc -ge $next.ToUniversalTime())
        worker_pid = $workerPid
        worker_process_started_at_utc = $workerProcessStartedAtUtc
        worker_process_started_at_source = $workerProcessStartedAtSource
    }
}

function Test-ProcessIdentityAlive {
    param(
        [int]$ProcessId = 0,
        [string]$ExpectedStartUtc = ""
    )
    if ($ProcessId -le 0) { return $false }
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        if ($ExpectedStartUtc) {
            $expected = [datetimeoffset]::MinValue
            if (-not [datetimeoffset]::TryParse(
                $ExpectedStartUtc,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::AssumeUniversal,
                [ref]$expected
            )) {
                return $true
            }
            $actual = [datetimeoffset]$process.StartTime.ToUniversalTime()
            if ([math]::Abs(($actual - $expected.ToUniversalTime()).TotalSeconds) -gt 2) { return $false }
        }
        return -not $process.HasExited
    } catch {
        return $false
    }
}

function Test-ExactByteArray {
    param(
        [byte[]]$Left,
        [byte[]]$Right
    )
    if ($null -eq $Left -or $null -eq $Right -or $Left.Length -ne $Right.Length) { return $false }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) { return $false }
    }
    return $true
}

function Read-ClaimSnapshot {
    if (-not (Test-Path -LiteralPath $CoordinatorClaimPath -PathType Leaf)) { return $null }
    try {
        $bytes = [IO.File]::ReadAllBytes($CoordinatorClaimPath)
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes).TrimStart([char]0xFEFF)
        $claim = $text | ConvertFrom-Json -DateKind String -ErrorAction Stop
    } catch {
        throw "coordinator claim JSON is invalid: $($_.Exception.Message)"
    }
    if ([string]$claim.schema -ne $claimSchema) {
        throw "coordinator claim schema mismatch: expected '$claimSchema', got '$([string]$claim.schema)'"
    }
    if (-not [string]$claim.coordinator_run_id) {
        throw "coordinator claim lacks coordinator_run_id"
    }
    $ownerPid = 0
    try { $ownerPid = [int]$claim.owner_pid } catch { }
    if ($ownerPid -le 0) { throw "coordinator claim has invalid owner_pid" }
    $ownerStartedAt = [datetimeoffset]::MinValue
    if (-not [string]$claim.owner_process_started_at_utc -or -not [datetimeoffset]::TryParse(
        [string]$claim.owner_process_started_at_utc,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$ownerStartedAt
    )) {
        throw "coordinator claim has invalid owner_process_started_at_utc"
    }
    if ([string]$claim.ownership_token -notmatch '^[0-9a-fA-F]{64}$') {
        throw "coordinator claim has invalid ownership_token"
    }
    return [pscustomobject]@{
        claim = $claim
        bytes = $bytes
        sha256 = Get-Sha256 -Bytes $bytes
        identity = [pscustomobject]@{
            schema = [string]$claim.schema
            coordinator_run_id = [string]$claim.coordinator_run_id
            owner_pid = $ownerPid
            owner_process_started_at_utc = [string]$claim.owner_process_started_at_utc
            ownership_token = [string]$claim.ownership_token
        }
    }
}

function Read-Claim {
    $snapshot = Read-ClaimSnapshot
    if (-not $snapshot) { return $null }
    return $snapshot.claim
}

function Archive-Claim {
    param(
        [string]$Reason,
        $ExpectedSnapshot,
        $ClaimMutexHandle
    )
    if (-not $ClaimMutexHandle) { throw "CLAIM_TRANSACTION_MUTEX_REQUIRED: stale archive is not mutex-protected" }
    if (-not $ExpectedSnapshot) { throw "CLAIM_RECOVERY_RACE: expected stale claim snapshot is missing" }
    if (-not (Test-Path -LiteralPath $CoordinatorClaimArchivePath)) {
        New-Item -ItemType Directory -Path $CoordinatorClaimArchivePath -Force | Out-Null
    }
    $stamp = [datetimeoffset]::UtcNow.ToString("yyyyMMddTHHmmssfffffffZ")
    $baseName = [IO.Path]::GetFileNameWithoutExtension($CoordinatorClaimPath)
    $destination = Join-Path $CoordinatorClaimArchivePath "$baseName.$Reason.$stamp.$([guid]::NewGuid().ToString('N')).json"
    try {
        $currentSnapshot = Read-ClaimSnapshot
    } catch {
        throw "CLAIM_RECOVERY_RACE: current claim cannot be verified: $($_.Exception.Message)"
    }
    if (-not $currentSnapshot) { throw "CLAIM_RECOVERY_RACE: claim disappeared before stale archive" }
    $mismatches = [System.Collections.Generic.List[string]]::new()
    if ([string]$currentSnapshot.sha256 -cne [string]$ExpectedSnapshot.sha256) { $mismatches.Add("sha256") }
    if (-not (Test-ExactByteArray -Left $currentSnapshot.bytes -Right $ExpectedSnapshot.bytes)) { $mismatches.Add("bytes") }
    foreach ($field in @("schema", "coordinator_run_id", "owner_pid", "owner_process_started_at_utc", "ownership_token")) {
        if ([string]$currentSnapshot.identity.$field -cne [string]$ExpectedSnapshot.identity.$field) {
            $mismatches.Add("identity.$field")
        }
    }
    if ($mismatches.Count -gt 0) {
        throw "CLAIM_RECOVERY_RACE: stale claim changed before archive: $($mismatches -join ',')"
    }
    [IO.File]::Move($CoordinatorClaimPath, $destination)
    return $destination
}

function Get-ClaimOwnershipSnapshot {
    param($Claim)
    return [pscustomobject]@{
        schema = [string]$Claim.schema
        coordinator_run_id = [string]$Claim.coordinator_run_id
        owner_pid = [int]$Claim.owner_pid
        owner_process_started_at_utc = [string]$Claim.owner_process_started_at_utc
        ownership_token = [string]$Claim.ownership_token
    }
}

function Assert-ClaimOwnership {
    param($ExpectedOwnership)
    $current = $null
    try {
        $current = Read-Claim
    } catch {
        throw "CLAIM_OWNERSHIP_LOST: $($_.Exception.Message)"
    }
    if (-not $current) {
        throw "CLAIM_OWNERSHIP_LOST: coordinator claim no longer exists"
    }
    $mismatches = [System.Collections.Generic.List[string]]::new()
    if ([string]$current.schema -cne [string]$ExpectedOwnership.schema) { $mismatches.Add("schema") }
    if ([string]$current.coordinator_run_id -cne [string]$ExpectedOwnership.coordinator_run_id) { $mismatches.Add("coordinator_run_id") }
    if ([int]$current.owner_pid -ne [int]$ExpectedOwnership.owner_pid) { $mismatches.Add("owner_pid") }
    if ([string]$current.owner_process_started_at_utc -cne [string]$ExpectedOwnership.owner_process_started_at_utc) { $mismatches.Add("owner_process_started_at_utc") }
    if ([string]$current.ownership_token -cne [string]$ExpectedOwnership.ownership_token) { $mismatches.Add("ownership_token") }
    if ($mismatches.Count -gt 0) {
        throw "CLAIM_OWNERSHIP_LOST: claim identity mismatch: $($mismatches -join ',')"
    }
    return $current
}

function Update-OwnedClaim {
    param(
        $ExpectedOwnership,
        [string]$Status,
        [AllowNull()][string]$ActiveTrack,
        [AllowNull()][Nullable[int]]$ActiveWorkerPid,
        [AllowNull()][string]$ActiveWorkerProcessStartedAtUtc
    )
    $claimMutexHandle = Enter-CoordinatorClaimMutex
    try {
        $claim = Assert-ClaimOwnership -ExpectedOwnership $ExpectedOwnership
        $claim.status = $Status
        $claim.active_track = $ActiveTrack
        $claim.active_worker_pid = $ActiveWorkerPid
        if ($claim.PSObject.Properties["active_worker_process_started_at_utc"]) {
            $claim.active_worker_process_started_at_utc = $ActiveWorkerProcessStartedAtUtc
        } else {
            $claim | Add-Member -NotePropertyName active_worker_process_started_at_utc -NotePropertyValue $ActiveWorkerProcessStartedAtUtc
        }
        [void](Assert-ClaimOwnership -ExpectedOwnership $ExpectedOwnership)
        Write-JsonAtomic -Path $CoordinatorClaimPath -Value $claim
        [void](Assert-ClaimOwnership -ExpectedOwnership $ExpectedOwnership)
    } finally {
        $claimMutexHandle.Dispose()
    }
}

function Archive-OwnedClaim {
    param(
        $ExpectedOwnership,
        [string]$Reason
    )
    $claimMutexHandle = Enter-CoordinatorClaimMutex
    try {
        [void](Assert-ClaimOwnership -ExpectedOwnership $ExpectedOwnership)
        $expectedSnapshot = Read-ClaimSnapshot
        if (-not $expectedSnapshot) { throw "CLAIM_OWNERSHIP_LOST: coordinator claim no longer exists" }
        [void](Assert-ClaimOwnership -ExpectedOwnership $ExpectedOwnership)
        return Archive-Claim -Reason $Reason -ExpectedSnapshot $expectedSnapshot -ClaimMutexHandle $claimMutexHandle
    } finally {
        $claimMutexHandle.Dispose()
    }
}

function Acquire-CoordinatorClaim {
    param(
        [string]$RunId,
        [datetimeoffset]$AcquiredAtUtc
    )
    $claimMutexHandle = $null
    try {
        $claimMutexHandle = Enter-CoordinatorClaimMutex
    } catch {
        return [pscustomobject]@{
            acquired = $false
            reason = "claim_transaction_mutex_busy"
            validation_error = $_.Exception.Message
            existing_claim = $null
            archived_stale_claim = $null
        }
    }
    try {
    Ensure-ParentDirectory -Path $CoordinatorClaimPath
    $archivedStaleClaim = $null
    if (Test-Path -LiteralPath $CoordinatorClaimPath -PathType Leaf) {
        try {
            $existingSnapshot = Read-ClaimSnapshot
            if (-not $existingSnapshot) { throw "CLAIM_RECOVERY_RACE: claim disappeared during inspection" }
            $existing = $existingSnapshot.claim
        } catch {
            if ($_.Exception.Message.StartsWith("CLAIM_RECOVERY_RACE:", [StringComparison]::Ordinal)) {
                return [pscustomobject]@{
                    acquired = $false
                    reason = "claim_recovery_race"
                    validation_error = $_.Exception.Message
                    existing_claim = $null
                    archived_stale_claim = $null
                }
            }
            return [pscustomobject]@{
                acquired = $false
                reason = "invalid_claim"
                validation_error = $_.Exception.Message
                existing_claim = $null
                archived_stale_claim = $null
            }
        }
        $activeWorkerPid = $null
        try { if ($existing.active_worker_pid) { $activeWorkerPid = [int]$existing.active_worker_pid } } catch { }
        $activeWorkerStartedAtUtc = $null
        if ($existing.PSObject.Properties["active_worker_process_started_at_utc"]) {
            $activeWorkerStartedAtUtc = [string]$existing.active_worker_process_started_at_utc
        }
        if (Test-ProcessIdentityAlive -ProcessId $activeWorkerPid -ExpectedStartUtc $activeWorkerStartedAtUtc) {
            return [pscustomobject]@{
                acquired = $false
                reason = "active_worker_alive"
                existing_claim = $existing
                archived_stale_claim = $null
            }
        }
        $ownerPid = $null
        try { if ($existing.owner_pid) { $ownerPid = [int]$existing.owner_pid } } catch { }
        if (Test-ProcessIdentityAlive -ProcessId $ownerPid -ExpectedStartUtc ([string]$existing.owner_process_started_at_utc)) {
            return [pscustomobject]@{
                acquired = $false
                reason = "coordinator_owner_alive"
                existing_claim = $existing
                archived_stale_claim = $null
            }
        }
        try {
            $archivedStaleClaim = Archive-Claim -Reason "stale" -ExpectedSnapshot $existingSnapshot -ClaimMutexHandle $claimMutexHandle
        } catch {
            $archiveFailureReason = if ($_.Exception.Message.StartsWith("CLAIM_RECOVERY_RACE:", [StringComparison]::Ordinal)) {
                "claim_recovery_race"
            } else {
                "claim_archive_race"
            }
            return [pscustomobject]@{
                acquired = $false
                reason = $archiveFailureReason
                validation_error = $_.Exception.Message
                existing_claim = $existing
                archived_stale_claim = $null
            }
        }
    }

    $owner = Get-Process -Id $PID
    $ownershipToken = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
    $claim = [ordered]@{
        schema = $claimSchema
        coordinator_run_id = $RunId
        owner_pid = $PID
        owner_process_started_at_utc = $owner.StartTime.ToUniversalTime().ToString("o")
        ownership_token = $ownershipToken
        acquired_at_utc = Get-UtcIso -Value $AcquiredAtUtc
        status = "RUNNING"
        active_track = $null
        active_worker_pid = $null
        active_worker_process_started_at_utc = $null
    }
    $bytes = ConvertTo-JsonBytes -Value $claim
    $stream = $null
    try {
        $stream = [IO.File]::Open($CoordinatorClaimPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } catch [IO.IOException] {
        try {
            $raceClaim = Read-Claim
        } catch {
            return [pscustomobject]@{
                acquired = $false
                reason = "invalid_claim"
                validation_error = $_.Exception.Message
                existing_claim = $null
                archived_stale_claim = $archivedStaleClaim
            }
        }
        return [pscustomobject]@{
            acquired = $false
            reason = "claim_create_race"
            existing_claim = $raceClaim
            archived_stale_claim = $archivedStaleClaim
        }
    } finally {
        if ($stream) { $stream.Dispose() }
    }
    return [pscustomobject]@{
        acquired = $true
        reason = "acquired"
        claim = $claim
        ownership = Get-ClaimOwnershipSnapshot -Claim $claim
        existing_claim = $null
        archived_stale_claim = $archivedStaleClaim
    }
    } finally {
        $claimMutexHandle.Dispose()
    }
}

function Resolve-PowerShellExecutable {
    $current = (Get-Process -Id $PID).Path
    if ($current -and (Test-Path -LiteralPath $current -PathType Leaf)) { return $current }
    foreach ($name in @("pwsh.exe", "pwsh", "powershell.exe", "powershell")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) { return $command.Source }
    }
    throw "PowerShell executable not found"
}

function Read-TrackStateEvidence {
    param([string]$Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { throw "track state is empty: $Path" }
    $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
    $state = $text | ConvertFrom-Json -DateKind String -ErrorAction Stop
    $workerPid = $null
    if ($state.PSObject.Properties["worker_pid"] -and $state.worker_pid) {
        try { $workerPid = [int]$state.worker_pid } catch { }
    }
    return [pscustomobject]@{
        hash = Get-Sha256 -Bytes $bytes
        state = $state
        status = [string]$state.status
        last_attempt_id = [string]$state.last_attempt_id
        last_finished_at_utc = [string]$state.last_finished_at_utc
        worker_pid = $workerPid
    }
}

function Test-FinishedMarkerAdvanced {
    param([string]$Before, [string]$After)
    if (-not $After) { return $false }
    $afterValue = [datetimeoffset]::MinValue
    if (-not [datetimeoffset]::TryParse($After, [ref]$afterValue)) { return $false }
    if (-not $Before) { return $true }
    $beforeValue = [datetimeoffset]::MinValue
    if (-not [datetimeoffset]::TryParse($Before, [ref]$beforeValue)) { return $true }
    return $afterValue.ToUniversalTime() -gt $beforeValue.ToUniversalTime()
}

function Invoke-TrackLauncher {
    param(
        [string]$Track,
        [string]$LauncherPath,
        [string]$StatePath,
        [datetimeoffset]$StartedAtUtc,
        $ClaimOwnership
    )
    $outcome = [ordered]@{
        track = $Track
        launcher_path = $LauncherPath
        started_at_utc = Get-UtcIso -Value $StartedAtUtc
        status = "RUNNING"
        launcher_status = $null
        launcher_exit_code = $null
        worker_pid = $null
        worker_exit_code = $null
        worker_wait_status = $null
        worker_exit_evidence_source = $null
        worker_exit_evidence_attempt_id = $null
        worker_exit_evidence_observed_at_utc = $null
        worker_exit_evidence_error = $null
        finished_at_utc = $null
        pre_state_sha256 = $null
        post_state_sha256 = $null
        pre_last_attempt_id = $null
        post_last_attempt_id = $null
        pre_last_finished_at_utc = $null
        post_last_finished_at_utc = $null
        state_advance_valid = $false
        post_state_status = $null
        error = $null
    }
    if (-not (Test-Path -LiteralPath $LauncherPath -PathType Leaf)) {
        $outcome.status = "LAUNCHER_MISSING"
        $outcome.error = "launcher not found: $LauncherPath"
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }

    try {
        $preEvidence = Read-TrackStateEvidence -Path $StatePath
        $outcome.pre_state_sha256 = $preEvidence.hash
        $outcome.pre_last_attempt_id = $preEvidence.last_attempt_id
        $outcome.pre_last_finished_at_utc = $preEvidence.last_finished_at_utc
    } catch {
        $outcome.status = "PRE_STATE_READ_FAILED"
        $outcome.error = $_.Exception.Message
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }

    $pwshExe = Resolve-PowerShellExecutable
    $previousLocation = Get-Location
    try {
        Set-Location -LiteralPath $repoRoot
        $nativeOutput = & $pwshExe -NoProfile -ExecutionPolicy Bypass -File $LauncherPath -ScheduledTick -Json 2>&1 | Out-String
        $outcome.launcher_exit_code = $LASTEXITCODE
    } catch {
        $outcome.status = "LAUNCHER_EXCEPTION"
        $outcome.error = $_.Exception.Message
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    } finally {
        Set-Location -LiteralPath $previousLocation.Path
    }

    try {
        $launcherPayload = $nativeOutput | ConvertFrom-Json -DateKind String -ErrorAction Stop
    } catch {
        $outcome.status = "INVALID_LAUNCHER_OUTPUT"
        $outcome.error = "launcher output is not JSON: " + $nativeOutput.Trim()
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }
    $outcome.launcher_status = [string]$launcherPayload.status
    if ($outcome.launcher_exit_code -ne 0) {
        $outcome.status = "LAUNCHER_FAILED"
        $outcome.error = "launcher exit code $($outcome.launcher_exit_code)"
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }
    if ([string]$launcherPayload.status -eq "NOT_DUE") {
        $outcome.status = "NOT_DUE_AFTER_RECHECK"
        $outcome.worker_wait_status = "NO_WORKER"
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }

    $workerPid = $null
    if ($launcherPayload.visible_terminal_pid) {
        try { $workerPid = [int]$launcherPayload.visible_terminal_pid } catch { }
    } elseif ([string]$launcherPayload.status -eq "ALREADY_RUNNING" -and $launcherPayload.worker_pid) {
        try { $workerPid = [int]$launcherPayload.worker_pid } catch { }
    }
    if (-not $workerPid -or $workerPid -le 0) {
        $outcome.status = "NO_VISIBLE_WORKER_PID"
        $outcome.error = "launcher status '$($launcherPayload.status)' did not return visible_terminal_pid"
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }

    $exitEvidenceFields = @(
        "visible_terminal_exit_pid",
        "visible_terminal_exit_code",
        "visible_terminal_exit_attempt_id",
        "visible_terminal_exit_observed_at_utc"
    )
    $providedExitEvidenceFields = @($exitEvidenceFields | Where-Object {
        $null -ne $launcherPayload.PSObject.Properties[$_]
    })
    if ($providedExitEvidenceFields.Count -gt 0) {
        if ($providedExitEvidenceFields.Count -ne $exitEvidenceFields.Count) {
            $outcome.worker_exit_evidence_error = "launcher exit evidence is incomplete"
        } else {
            try {
                $reportedExitPid = [int]$launcherPayload.visible_terminal_exit_pid
                $reportedExitCode = [int]$launcherPayload.visible_terminal_exit_code
                $reportedExitAttemptId = [string]$launcherPayload.visible_terminal_exit_attempt_id
                $reportedExitObservedAt = [datetimeoffset]::MinValue
                if ($reportedExitPid -ne $workerPid) {
                    throw "launcher exit evidence PID mismatch"
                }
                if (-not $reportedExitAttemptId) {
                    throw "launcher exit evidence attempt_id is missing"
                }
                if (-not [datetimeoffset]::TryParse(
                    [string]$launcherPayload.visible_terminal_exit_observed_at_utc,
                    [ref]$reportedExitObservedAt
                )) {
                    throw "launcher exit evidence observed_at is invalid"
                }
                $outcome.worker_exit_code = $reportedExitCode
                $outcome.worker_exit_evidence_source = "LAUNCHER_REPORTED"
                $outcome.worker_exit_evidence_attempt_id = $reportedExitAttemptId
                $outcome.worker_exit_evidence_observed_at_utc = $reportedExitObservedAt.ToUniversalTime().ToString("o")
            } catch {
                $outcome.worker_exit_code = $null
                $outcome.worker_exit_evidence_error = $_.Exception.Message
            }
        }
    }

    $workerProcess = $null
    $workerProcessStartedAtUtc = $null
    try {
        $workerProcess = [Diagnostics.Process]::GetProcessById($workerPid)
        $workerProcessStartedAtUtc = $workerProcess.StartTime.ToUniversalTime().ToString("o")
    } catch {
        $outcome.worker_wait_status = "ALREADY_EXITED"
    }
    $outcome.worker_pid = $workerPid
    try {
        Update-OwnedClaim `
            -ExpectedOwnership $ClaimOwnership `
            -Status "WAITING_VISIBLE_WORKER" `
            -ActiveTrack $Track `
            -ActiveWorkerPid $workerPid `
            -ActiveWorkerProcessStartedAtUtc $workerProcessStartedAtUtc
    } catch {
        $outcome.status = "CLAIM_OWNERSHIP_LOST"
        $outcome.error = $_.Exception.Message
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }
    if ($workerProcess) {
        $timeoutMs = $WorkerExitTimeoutSec * 1000
        if (-not $workerProcess.WaitForExit($timeoutMs)) {
            $outcome.status = "WORKER_TIMEOUT"
            $outcome.worker_wait_status = "TIMEOUT"
            $outcome.error = "visible worker $workerPid did not exit within $WorkerExitTimeoutSec seconds"
            $outcome.finished_at_utc = Get-UtcIso
            return [pscustomobject]$outcome
        }
        $outcome.worker_wait_status = "EXITED"
        try {
            $outcome.worker_exit_code = $workerProcess.ExitCode
            $outcome.worker_exit_evidence_source = "PROCESS_HANDLE"
            $outcome.worker_exit_evidence_attempt_id = $null
            $outcome.worker_exit_evidence_observed_at_utc = Get-UtcIso
            $outcome.worker_exit_evidence_error = $null
        } catch { }
    }

    try {
        Update-OwnedClaim `
            -ExpectedOwnership $ClaimOwnership `
            -Status "RUNNING" `
            -ActiveTrack $null `
            -ActiveWorkerPid $null `
            -ActiveWorkerProcessStartedAtUtc $null
    } catch {
        $outcome.status = "CLAIM_OWNERSHIP_LOST"
        $outcome.error = $_.Exception.Message
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }
    try {
        $postEvidence = Read-TrackStateEvidence -Path $StatePath
        $postState = $postEvidence.state
        $outcome.post_state_sha256 = $postEvidence.hash
        $outcome.post_state_status = $postEvidence.status
        $outcome.post_last_attempt_id = $postEvidence.last_attempt_id
        $outcome.post_last_finished_at_utc = $postEvidence.last_finished_at_utc
    } catch {
        $outcome.status = "POST_STATE_READ_FAILED"
        $outcome.error = $_.Exception.Message
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }

    if ($outcome.worker_wait_status -eq "ALREADY_EXITED") {
        if ($outcome.worker_exit_evidence_source -ne "LAUNCHER_REPORTED") {
            $outcome.status = "WORKER_EXIT_UNKNOWN"
            $evidenceDetail = if ($outcome.worker_exit_evidence_error) {
                ": $($outcome.worker_exit_evidence_error)"
            } else { "" }
            $outcome.error = "visible worker $workerPid exited before attach without exact exit evidence$evidenceDetail"
            $outcome.finished_at_utc = Get-UtcIso
            return [pscustomobject]$outcome
        }
        if ([string]$outcome.worker_exit_evidence_attempt_id -cne [string]$postEvidence.last_attempt_id) {
            $outcome.status = "WORKER_EXIT_UNKNOWN"
            $outcome.error = "launcher exit evidence attempt_id does not match terminal track state"
            $outcome.finished_at_utc = Get-UtcIso
            return [pscustomobject]$outcome
        }
    }

    $evidenceFailures = [System.Collections.Generic.List[string]]::new()
    $terminalStatuses = @("COMPLETE", "RETRY_NEXT_INTERVAL", "PARTIAL_RETRY_NEXT_INTERVAL", "DEFERRED_NEXT_INTERVAL", "FAILED", "STOPPED_INCOMPLETE")
    if ($postEvidence.hash -eq $preEvidence.hash) { $evidenceFailures.Add("state_hash_unchanged") }
    if ($postEvidence.worker_pid) { $evidenceFailures.Add("worker_pid_not_cleared") }
    if ($postEvidence.status -notin $terminalStatuses) { $evidenceFailures.Add("state_not_terminal:$($postEvidence.status)") }
    if ([string]$launcherPayload.status -eq "ALREADY_RUNNING") {
        if (-not (Test-FinishedMarkerAdvanced -Before $preEvidence.last_finished_at_utc -After $postEvidence.last_finished_at_utc)) {
            $evidenceFailures.Add("finished_marker_not_advanced")
        }
    } elseif (-not $postEvidence.last_attempt_id -or $postEvidence.last_attempt_id -eq $preEvidence.last_attempt_id) {
        $evidenceFailures.Add("last_attempt_id_not_advanced")
    }
    if ($evidenceFailures.Count -gt 0) {
        $outcome.status = "STALE_TRACK_STATE"
        $outcome.error = $evidenceFailures -join ";"
        $outcome.finished_at_utc = Get-UtcIso
        return [pscustomobject]$outcome
    }
    $outcome.state_advance_valid = $true

    if ($null -ne $outcome.worker_exit_code -and [int]$outcome.worker_exit_code -ne 0) {
        $outcome.status = "WORKER_FAILED"
        $outcome.error = "visible worker exit code $($outcome.worker_exit_code)"
    } elseif ($outcome.post_state_status -in @("RETRY_NEXT_INTERVAL", "PARTIAL_RETRY_NEXT_INTERVAL")) {
        $outcome.status = [string]$outcome.post_state_status
    } elseif ($outcome.post_state_status -eq "COMPLETE") {
        $outcome.status = "COMPLETE"
    } else {
        $outcome.status = "RETRY_NEXT_INTERVAL"
        $outcome.error = "terminal track state: $($outcome.post_state_status)"
    }
    $outcome.finished_at_utc = Get-UtcIso
    return [pscustomobject]$outcome
}

function Publish-Result {
    param($Payload, [int]$ExitCode)
    $Payload | ConvertTo-Json -Depth 40
    exit $ExitCode
}

function Persist-CoordinatorTerminalEvidence {
    param(
        [string]$RunId,
        [string]$AttemptId,
        [datetimeoffset]$EvaluatedAtUtc,
        [string]$Status,
        [string]$Reason,
        [AllowNull()][string]$ErrorMessage,
        [object[]]$DueTracks = @(),
        [object[]]$TrackOutcomes = @(),
        [bool]$PendingRetry = $true,
        [AllowNull()][string]$ClaimFailureReason,
        [AllowNull()][string]$NextDueAtUtc,
        [bool]$RetainedClaim = $false
    )
    $finishedAt = [datetimeoffset]::UtcNow
    $attempt = [ordered]@{
        schema = $attemptSchema
        record_kind = "TERMINAL"
        terminal = $true
        attempt_id = $AttemptId
        coordinator_run_id = $RunId
        status = $Status
        reason = $Reason
        started_at_utc = Get-UtcIso -Value $EvaluatedAtUtc
        finished_at_utc = Get-UtcIso -Value $finishedAt
        evaluated_at_utc = Get-UtcIso -Value $EvaluatedAtUtc
        due_tracks = @($DueTracks)
        track_outcomes = @($TrackOutcomes)
        pending_retry = $PendingRetry
        retained_claim_for_active_worker = $RetainedClaim
    }
    $state = [ordered]@{
        schema = $coordinatorSchema
        status = $Status
        reason = $Reason
        coordinator_run_id = $RunId
        last_attempt_id = $AttemptId
        evaluated_at_utc = Get-UtcIso -Value $EvaluatedAtUtc
        started_at_utc = Get-UtcIso -Value $EvaluatedAtUtc
        finished_at_utc = Get-UtcIso -Value $finishedAt
        due_tracks = @($DueTracks)
        track_outcomes = @($TrackOutcomes)
        pending_retry = $PendingRetry
        retained_claim_for_active_worker = $RetainedClaim
        state_paths = [ordered]@{
            listing = $ListingStatePath
            premarket = $PremarketStatePath
            preipo = $PreipoStatePath
        }
        attempts_path = $CoordinatorAttemptsPath
        claim_path = $CoordinatorClaimPath
        claim_archive_path = $CoordinatorClaimArchivePath
    }
    if ($ErrorMessage) {
        $attempt["error"] = $ErrorMessage
        $state["error"] = $ErrorMessage
    }
    if ($ClaimFailureReason) {
        $attempt["claim_failure_reason"] = $ClaimFailureReason
        $state["claim_failure_reason"] = $ClaimFailureReason
    }
    if ($NextDueAtUtc) {
        $attempt["next_due_at_utc"] = $NextDueAtUtc
        $state["next_due_at_utc"] = $NextDueAtUtc
    }

    $result = [ordered]@{
        attempt_persisted = $false
        state_persisted = $false
        persistence_error = $null
    }
    try {
        # Ledger-first: mutable state must never advertise a terminal result
        # without matching append-only evidence for the same attempt id.
        Append-Attempt -Value $attempt
        $result.attempt_persisted = $true
    } catch {
        $result.persistence_error = "attempt: $($_.Exception.Message)"
        return [pscustomobject]$result
    }
    try {
        Write-JsonAtomic -Path $CoordinatorStatePath -Value $state
        $result.state_persisted = $true
    } catch {
        $result.persistence_error = "state: $($_.Exception.Message)"
    }
    return [pscustomobject]$result
}

function Read-CoordinatorAttemptRecords {
    if (-not (Test-Path -LiteralPath $CoordinatorAttemptsPath -PathType Leaf)) {
        return @()
    }
    $records = [System.Collections.Generic.List[object]]::new()
    foreach ($line in [IO.File]::ReadAllLines($CoordinatorAttemptsPath)) {
        if (-not $line.Trim()) { continue }
        try {
            $records.Add(($line | ConvertFrom-Json -DateKind String -ErrorAction Stop))
        } catch {
            throw "coordinator attempt ledger JSON is invalid: $($_.Exception.Message)"
        }
    }
    return @($records)
}

function Repair-OrphanedCoordinatorAttempt {
    param(
        [AllowNull()][string]$ArchivedStaleClaimPath,
        [datetimeoffset]$RecoveredAtUtc
    )
    if (-not $ArchivedStaleClaimPath) { return $null }
    if (-not (Test-Path -LiteralPath $ArchivedStaleClaimPath -PathType Leaf)) {
        throw "archived stale coordinator claim is missing: $ArchivedStaleClaimPath"
    }
    try {
        $archivedClaim = Get-Content -Raw -LiteralPath $ArchivedStaleClaimPath | ConvertFrom-Json -DateKind String -ErrorAction Stop
    } catch {
        throw "archived stale coordinator claim is invalid: $($_.Exception.Message)"
    }
    $orphanAttemptId = [string]$archivedClaim.coordinator_run_id
    if (-not $orphanAttemptId) { throw "archived stale coordinator claim lacks coordinator_run_id" }
    $matching = @(Read-CoordinatorAttemptRecords | Where-Object { [string]$_.attempt_id -ceq $orphanAttemptId })
    $running = @($matching | Where-Object { [string]$_.status -ceq "RUNNING" })
    $terminal = @($matching | Where-Object { [string]$_.status -cne "RUNNING" })
    if ($running.Count -eq 0 -or $terminal.Count -gt 0) { return $null }

    $recovery = [ordered]@{
        schema = $attemptSchema
        record_kind = "TERMINAL_RECOVERY"
        terminal = $true
        attempt_id = $orphanAttemptId
        coordinator_run_id = $orphanAttemptId
        status = "RETRY_NEXT_INTERVAL"
        reason = "ORPHANED_COORDINATOR_RUN_RECOVERED"
        started_at_utc = $running[0].started_at_utc
        finished_at_utc = Get-UtcIso -Value $RecoveredAtUtc
        pending_retry = $true
        recovered_from_claim_archive_path = $ArchivedStaleClaimPath
    }
    Append-Attempt -Value $recovery
    return [pscustomobject]$recovery
}

$now = $null
try {
    $now = Resolve-NowUtc
} catch {
    Publish-Result -Payload ([ordered]@{
        schema = $coordinatorSchema
        status = "RETRY_NEXT_INTERVAL"
        error = $_.Exception.Message
    }) -ExitCode 2
}

$legacyTopology = Read-LegacyAutomationTopology
if (-not $legacyTopology.valid) {
    Publish-Result -Payload ([ordered]@{
        schema = $coordinatorSchema
        status = "BLOCKED_LEGACY_AUTOMATIONS"
        reason = "LEGACY_AUTOMATION_TOPOLOGY_INVALID"
        evaluated_at_utc = Get-UtcIso -Value $now
        codex_automations_root = $CodexAutomationsRoot
        execution_performed = $false
        legacy_automations = @($legacyTopology.automations)
        validation_errors = @($legacyTopology.validation_errors)
    }) -ExitCode 2
}

$runId = "listing_strategy_due_" + $now.ToString("yyyyMMddTHHmmssfffffffZ") + "_" + [guid]::NewGuid().ToString("N")
$attemptId = $runId
$snapshots = [System.Collections.Generic.List[object]]::new()
try {
    foreach ($track in $trackOrder) {
        $definition = $trackDefinitions[$track]
        $snapshots.Add((Read-TrackState -Track $track -Path $definition.state_path -ReferenceUtc $now))
    }
} catch {
    $trackStateError = $_.Exception.Message
    $persistence = Persist-CoordinatorTerminalEvidence `
        -RunId $runId `
        -AttemptId $attemptId `
        -EvaluatedAtUtc $now `
        -Status "RETRY_NEXT_INTERVAL" `
        -Reason "TRACK_STATE_READ_FAILED" `
        -ErrorMessage $trackStateError `
        -PendingRetry $true
    $payload = [ordered]@{
        schema = $coordinatorSchema
        status = "RETRY_NEXT_INTERVAL"
        reason = "TRACK_STATE_READ_FAILED"
        coordinator_run_id = $runId
        evaluated_at_utc = Get-UtcIso -Value $now
        due_tracks = @()
        pending_retry = $true
        error = $trackStateError
        coordinator_state_path = $CoordinatorStatePath
        coordinator_attempts_path = $CoordinatorAttemptsPath
    }
    if ($persistence.persistence_error) {
        $payload["persistence_error"] = $persistence.persistence_error
    }
    Publish-Result -Payload $payload -ExitCode 2
}

$dueTracks = @($snapshots | Where-Object { $_.due } | ForEach-Object { $_.track })
$nextDue = @($snapshots | Sort-Object next_interval_at_utc | Select-Object -First 1)[0].next_interval_at_utc
if ($dueTracks.Count -eq 0) {
    Publish-Result -Payload ([ordered]@{
        schema = $coordinatorSchema
        status = "NOT_DUE"
        coordinator_run_id = $runId
        evaluated_at_utc = Get-UtcIso -Value $now
        due_tracks = @()
        next_due_at_utc = Get-UtcIso -Value $nextDue
        track_outcomes = @()
        legacy_automations = @($legacyTopology.automations)
        state_inputs = @($snapshots | ForEach-Object {
            [ordered]@{
                track = $_.track
                state_path = $_.path
                state_sha256 = $_.state_sha256
                next_interval_at_utc = Get-UtcIso -Value $_.next_interval_at_utc
            }
        })
    }) -ExitCode 0
}

$claimResult = Acquire-CoordinatorClaim -RunId $runId -AcquiredAtUtc $now
if (-not $claimResult.acquired) {
    if ($claimResult.reason -eq "invalid_claim") {
        $invalidClaimPersistence = Persist-CoordinatorTerminalEvidence `
            -RunId $runId `
            -AttemptId $attemptId `
            -EvaluatedAtUtc $now `
            -Status "BLOCKED_INVALID_COORDINATOR_CLAIM" `
            -Reason "INVALID_COORDINATOR_CLAIM" `
            -ErrorMessage ([string]$claimResult.validation_error) `
            -DueTracks $dueTracks `
            -PendingRetry $true `
            -ClaimFailureReason "invalid_claim" `
            -NextDueAtUtc (Get-UtcIso -Value $nextDue) `
            -RetainedClaim $true
        $invalidClaimPayload = [ordered]@{
            schema = $coordinatorSchema
            status = "BLOCKED_INVALID_COORDINATOR_CLAIM"
            reason = "INVALID_COORDINATOR_CLAIM"
            claim_failure_reason = $claimResult.reason
            validation_error = $claimResult.validation_error
            coordinator_run_id = $runId
            claim_path = $CoordinatorClaimPath
            pending_retry = $true
            coordinator_state_path = $CoordinatorStatePath
            coordinator_attempts_path = $CoordinatorAttemptsPath
        }
        if ($invalidClaimPersistence.persistence_error) {
            $invalidClaimPayload["persistence_error"] = $invalidClaimPersistence.persistence_error
        }
        Publish-Result -Payload $invalidClaimPayload -ExitCode 2
    }
    $readOnlyNonAcquiredReasons = @(
        "claim_transaction_mutex_busy",
        "claim_recovery_race",
        "claim_create_race"
    )
    if ($claimResult.reason -in $readOnlyNonAcquiredReasons) {
        $readOnlyFailureReason = if ($claimResult.reason -eq "claim_recovery_race") {
            "CLAIM_RECOVERY_RACE"
        } else {
            "COORDINATOR_CLAIM_RECOVERY_FAILED"
        }
        Publish-Result -Payload ([ordered]@{
            schema = $coordinatorSchema
            status = "RETRY_NEXT_INTERVAL"
            reason = $readOnlyFailureReason
            claim_failure_reason = $claimResult.reason
            coordinator_run_id = $runId
            evaluated_at_utc = Get-UtcIso -Value $now
            due_tracks = $dueTracks
            track_outcomes = @()
            pending_retry = $true
            next_due_at_utc = Get-UtcIso -Value $nextDue
            claim_path = $CoordinatorClaimPath
            persistence_skipped = "NON_ACQUIRED_LIVE_RACE_READ_ONLY"
        }) -ExitCode 2
    }
    $benignDuplicateReasons = @("active_worker_alive", "coordinator_owner_alive")
    if ($claimResult.reason -notin $benignDuplicateReasons) {
        $claimFailureReason = if ($claimResult.reason -eq "claim_recovery_race") {
            "CLAIM_RECOVERY_RACE"
        } else {
            "COORDINATOR_CLAIM_RECOVERY_FAILED"
        }
        $claimFailurePayload = [ordered]@{
            schema = $coordinatorSchema
            status = "RETRY_NEXT_INTERVAL"
            reason = $claimFailureReason
            claim_failure_reason = $claimResult.reason
            coordinator_run_id = $runId
            evaluated_at_utc = Get-UtcIso -Value $now
            due_tracks = $dueTracks
            track_outcomes = @()
            pending_retry = $true
            next_due_at_utc = Get-UtcIso -Value $nextDue
            claim_path = $CoordinatorClaimPath
        }
        $claimFailurePersistence = Persist-CoordinatorTerminalEvidence `
            -RunId $runId `
            -AttemptId $attemptId `
            -EvaluatedAtUtc $now `
            -Status "RETRY_NEXT_INTERVAL" `
            -Reason $claimFailureReason `
            -ErrorMessage ([string]$claimResult.validation_error) `
            -DueTracks $dueTracks `
            -PendingRetry $true `
            -ClaimFailureReason ([string]$claimResult.reason) `
            -NextDueAtUtc (Get-UtcIso -Value $nextDue) `
            -RetainedClaim $true
        if ($claimFailurePersistence.persistence_error) {
            $claimFailurePayload["persistence_error"] = $claimFailurePersistence.persistence_error
        }
        $claimFailurePayload["coordinator_state_path"] = $CoordinatorStatePath
        $claimFailurePayload["coordinator_attempts_path"] = $CoordinatorAttemptsPath
        Publish-Result -Payload $claimFailurePayload -ExitCode 2
    }
    $existingWorkerPid = $null
    $existingRunId = $null
    if ($claimResult.existing_claim) {
        $existingWorkerPid = $claimResult.existing_claim.active_worker_pid
        $existingRunId = $claimResult.existing_claim.coordinator_run_id
    }
    Publish-Result -Payload ([ordered]@{
        schema = $coordinatorSchema
        status = "COORDINATOR_ALREADY_RUNNING"
        reason = $claimResult.reason
        coordinator_run_id = $existingRunId
        active_worker_pid = $existingWorkerPid
        claim_path = $CoordinatorClaimPath
    }) -ExitCode 0
}

$startedAt = [datetimeoffset]::UtcNow
$terminalPayload = $null
$terminalExitCode = 0
$retainClaim = $false
$claimOwnershipLost = $false
$claimOwnership = $claimResult.ownership
$outcomes = [System.Collections.Generic.List[object]]::new()

try {
    [void](Assert-ClaimOwnership -ExpectedOwnership $claimOwnership)
    $orphanRecovery = Repair-OrphanedCoordinatorAttempt `
        -ArchivedStaleClaimPath ([string]$claimResult.archived_stale_claim) `
        -RecoveredAtUtc ([datetimeoffset]::UtcNow)
    $recoveredOrphanAttemptId = if ($orphanRecovery) { [string]$orphanRecovery.attempt_id } else { $null }
    Append-Attempt -Value ([ordered]@{
        schema = $attemptSchema
        attempt_id = $attemptId
        coordinator_run_id = $runId
        status = "RUNNING"
        started_at_utc = Get-UtcIso -Value $startedAt
        evaluated_at_utc = Get-UtcIso -Value $now
        stale_claim_archive_path = $claimResult.archived_stale_claim
        recovered_orphan_attempt_id = $recoveredOrphanAttemptId
    })

    $liveTrackWorkers = @($snapshots | Where-Object {
        $_.worker_pid -and (Test-ProcessIdentityAlive `
            -ProcessId ([int]$_.worker_pid) `
            -ExpectedStartUtc ([string]$_.worker_process_started_at_utc))
    })

    if ($liveTrackWorkers.Count -gt 0) {
        $terminalPayload = [ordered]@{
            schema = $coordinatorSchema
            status = "ACTIVE_TRACK_WORKER_PRESENT"
            coordinator_run_id = $runId
            evaluated_at_utc = Get-UtcIso -Value $now
            due_tracks = $dueTracks
            live_track_workers = @($liveTrackWorkers | ForEach-Object {
                [ordered]@{
                    track = $_.track
                    worker_pid = $_.worker_pid
                    worker_process_started_at_utc = $_.worker_process_started_at_utc
                    worker_process_started_at_source = $_.worker_process_started_at_source
                }
            })
            next_due_at_utc = Get-UtcIso -Value $nextDue
            track_outcomes = @()
        }
    } else {
        foreach ($track in $dueTracks) {
            $definition = $trackDefinitions[$track]
            $outcome = Invoke-TrackLauncher `
                -Track $track `
                -LauncherPath $definition.launcher_path `
                -StatePath $definition.state_path `
                -StartedAtUtc ([datetimeoffset]::UtcNow) `
                -ClaimOwnership $claimOwnership
            $outcomes.Add($outcome)
            if ($outcome.status -eq "WORKER_TIMEOUT") {
                $retainClaim = $true
                break
            }
            if ($outcome.status -eq "CLAIM_OWNERSHIP_LOST") {
                $claimOwnershipLost = $true
                $retainClaim = $true
                break
            }
        }
        $successfulOutcomes = @($outcomes | Where-Object { $_.status -in @("COMPLETE", "NOT_DUE_AFTER_RECHECK") })
        $failedOutcomes = @($outcomes | Where-Object { $_.status -notin @("COMPLETE", "NOT_DUE_AFTER_RECHECK") })
        $finalStatus = if ($failedOutcomes.Count -eq 0) {
            "COMPLETE"
        } elseif ($successfulOutcomes.Count -gt 0) {
            "PARTIAL_RETRY_NEXT_INTERVAL"
        } else {
            "RETRY_NEXT_INTERVAL"
        }
        $terminalExitCode = if ($failedOutcomes.Count -eq 0) { 0 } else { 2 }
        $terminalPayload = [ordered]@{
            schema = $coordinatorSchema
            status = $finalStatus
            coordinator_run_id = $runId
            evaluated_at_utc = Get-UtcIso -Value $now
            due_tracks = $dueTracks
            track_outcomes = @($outcomes)
            pending_retry = ($failedOutcomes.Count -gt 0)
            retained_claim_for_active_worker = $retainClaim
        }
        if ($claimOwnershipLost) {
            $terminalPayload["reason"] = "CLAIM_OWNERSHIP_LOST"
            $terminalPayload["claim_ownership_lost"] = $true
        }
    }
} catch {
    $terminalExitCode = 2
    $caughtOwnershipLoss = $_.Exception.Message.StartsWith("CLAIM_OWNERSHIP_LOST:", [StringComparison]::Ordinal)
    if ($caughtOwnershipLoss) {
        $claimOwnershipLost = $true
        $retainClaim = $true
    }
    $terminalPayload = [ordered]@{
        schema = $coordinatorSchema
        status = "RETRY_NEXT_INTERVAL"
        coordinator_run_id = $runId
        evaluated_at_utc = Get-UtcIso -Value $now
        due_tracks = $dueTracks
        track_outcomes = @($outcomes)
        pending_retry = $true
        error = $_.Exception.Message
    }
    if ($caughtOwnershipLoss) {
        $terminalPayload["reason"] = "CLAIM_OWNERSHIP_LOST"
        $terminalPayload["claim_ownership_lost"] = $true
    }
} finally {
    if (-not $terminalPayload) {
        $terminalExitCode = 2
        $terminalPayload = [ordered]@{
            schema = $coordinatorSchema
            status = "RETRY_NEXT_INTERVAL"
            coordinator_run_id = $runId
            evaluated_at_utc = Get-UtcIso -Value $now
            due_tracks = @()
            track_outcomes = @($outcomes)
            pending_retry = $true
            error = "coordinator produced no terminal payload"
        }
    }
    if (-not $claimOwnershipLost) {
        try {
            [void](Assert-ClaimOwnership -ExpectedOwnership $claimOwnership)
        } catch {
            $terminalExitCode = 2
            $terminalPayload.status = "RETRY_NEXT_INTERVAL"
            $terminalPayload.pending_retry = $true
            $terminalPayload["reason"] = "CLAIM_OWNERSHIP_LOST"
            $terminalPayload["claim_ownership_lost"] = $true
            $terminalPayload["persistence_error"] = $_.Exception.Message
            $claimOwnershipLost = $true
            $retainClaim = $true
        }
    }
    if ($claimOwnershipLost) {
        $terminalExitCode = 2
        $terminalPayload.status = "RETRY_NEXT_INTERVAL"
        $terminalPayload.pending_retry = $true
        $terminalPayload["reason"] = "CLAIM_OWNERSHIP_LOST"
        $terminalPayload["claim_ownership_lost"] = $true
        $retainClaim = $true
        $finishedAt = [datetimeoffset]::UtcNow
        try {
            Append-Attempt -Value ([ordered]@{
                schema = $attemptSchema
                record_kind = "TERMINAL"
                attempt_id = $attemptId
                coordinator_run_id = $runId
                status = "RETRY_NEXT_INTERVAL"
                reason = "CLAIM_OWNERSHIP_LOST"
                started_at_utc = Get-UtcIso -Value $startedAt
                finished_at_utc = Get-UtcIso -Value $finishedAt
                evaluated_at_utc = Get-UtcIso -Value $now
                due_tracks = @($terminalPayload.due_tracks)
                track_outcomes = @($terminalPayload.track_outcomes)
                pending_retry = $true
                retained_claim_for_active_worker = $true
                claim_ownership_lost = $true
            })
        } catch {
            $terminalPayload["persistence_error"] = "ownership-loss terminal append failed: $($_.Exception.Message)"
        }
    }
    if (-not $claimOwnershipLost) {
        $finishedAt = [datetimeoffset]::UtcNow
        $coordinatorState = [ordered]@{
            schema = $coordinatorSchema
            status = $terminalPayload.status
            coordinator_run_id = $runId
            last_attempt_id = $attemptId
            evaluated_at_utc = Get-UtcIso -Value $now
            started_at_utc = Get-UtcIso -Value $startedAt
            finished_at_utc = Get-UtcIso -Value $finishedAt
            due_tracks = @($terminalPayload.due_tracks)
            track_outcomes = @($terminalPayload.track_outcomes)
            pending_retry = [bool]$terminalPayload.pending_retry
            retained_claim_for_active_worker = $retainClaim
            state_paths = [ordered]@{
                listing = $ListingStatePath
                premarket = $PremarketStatePath
                preipo = $PreipoStatePath
            }
            attempts_path = $CoordinatorAttemptsPath
            claim_path = $CoordinatorClaimPath
            claim_archive_path = $CoordinatorClaimArchivePath
        }
        $persistencePhase = "terminal_attempt_append"
        $terminalAttemptPersisted = $false
        try {
            Append-Attempt -Value ([ordered]@{
                schema = $attemptSchema
                attempt_id = $attemptId
                coordinator_run_id = $runId
                status = $terminalPayload.status
                started_at_utc = Get-UtcIso -Value $startedAt
                finished_at_utc = Get-UtcIso -Value $finishedAt
                evaluated_at_utc = Get-UtcIso -Value $now
                due_tracks = @($terminalPayload.due_tracks)
                track_outcomes = @($terminalPayload.track_outcomes)
                pending_retry = [bool]$terminalPayload.pending_retry
                retained_claim_for_active_worker = $retainClaim
            })
            $terminalAttemptPersisted = $true
            $persistencePhase = "coordinator_state_write"
            Write-JsonAtomic -Path $CoordinatorStatePath -Value $coordinatorState
            if (-not $retainClaim) {
                $persistencePhase = "claim_release_archive"
                $archiveReason = if ($terminalExitCode -eq 0) { "completed" } else { "failed" }
                [void](Archive-OwnedClaim -ExpectedOwnership $claimOwnership -Reason $archiveReason)
            }
        } catch {
            $persistenceFailure = $_.Exception.Message
            $failedPersistencePhase = $persistencePhase
            $terminalExitCode = 2
            $terminalPayload.status = "RETRY_NEXT_INTERVAL"
            $terminalPayload.pending_retry = $true
            $terminalPayload.persistence_error = $persistenceFailure
            if ($persistenceFailure.StartsWith("CLAIM_OWNERSHIP_LOST:", [StringComparison]::Ordinal)) {
                $terminalPayload["reason"] = "CLAIM_OWNERSHIP_LOST"
                $terminalPayload["claim_ownership_lost"] = $true
                $claimOwnershipLost = $true
            } elseif ($failedPersistencePhase -eq "claim_release_archive") {
                $failureReason = "COORDINATOR_CLAIM_RELEASE_FAILED"
                $priorTerminalStatus = [string]$coordinatorState.status
                $correctionAt = [datetimeoffset]::UtcNow
                $terminalPayload["reason"] = $failureReason
                $terminalPayload["claim_release_error"] = $persistenceFailure
                $terminalPayload["claim_retained_due_to_release_failure"] = $true

                $coordinatorState.status = "RETRY_NEXT_INTERVAL"
                $coordinatorState.finished_at_utc = Get-UtcIso -Value $correctionAt
                $coordinatorState.pending_retry = $true
                $coordinatorState.retained_claim_for_active_worker = $true
                $coordinatorState["reason"] = $failureReason
                $coordinatorState["prior_terminal_status"] = $priorTerminalStatus
                $coordinatorState["claim_release_error"] = $persistenceFailure
                $coordinatorState["claim_retained_due_to_release_failure"] = $true
                $correctionErrors = [System.Collections.Generic.List[string]]::new()
                try {
                    Append-Attempt -Value ([ordered]@{
                        schema = $attemptSchema
                        record_kind = "TERMINAL_CORRECTION"
                        attempt_id = "$attemptId.claim_release_failure"
                        corrects_attempt_id = $attemptId
                        coordinator_run_id = $runId
                        status = "RETRY_NEXT_INTERVAL"
                        prior_terminal_status = $priorTerminalStatus
                        reason = $failureReason
                        claim_release_error = $persistenceFailure
                        started_at_utc = Get-UtcIso -Value $startedAt
                        finished_at_utc = Get-UtcIso -Value $correctionAt
                        evaluated_at_utc = Get-UtcIso -Value $now
                        due_tracks = @($terminalPayload.due_tracks)
                        track_outcomes = @($terminalPayload.track_outcomes)
                        pending_retry = $true
                        retained_claim_for_active_worker = $true
                        claim_retained_due_to_release_failure = $true
                    })
                } catch {
                    $correctionErrors.Add("ledger: $($_.Exception.Message)")
                }
                try {
                    Write-JsonAtomic -Path $CoordinatorStatePath -Value $coordinatorState
                } catch {
                    $correctionErrors.Add("state: $($_.Exception.Message)")
                }
                if ($correctionErrors.Count -gt 0) {
                    $terminalPayload["durability_correction_error"] = $correctionErrors -join " | "
                }
            } else {
                $failureReason = "COORDINATOR_PERSISTENCE_FAILED"
                $priorTerminalStatus = [string]$coordinatorState.status
                $correctionAt = [datetimeoffset]::UtcNow
                $terminalPayload["reason"] = $failureReason
                $terminalPayload["persistence_phase"] = $failedPersistencePhase
                $coordinatorState.status = "RETRY_NEXT_INTERVAL"
                $coordinatorState.finished_at_utc = Get-UtcIso -Value $correctionAt
                $coordinatorState.pending_retry = $true
                $coordinatorState.retained_claim_for_active_worker = $true
                $coordinatorState["reason"] = $failureReason
                $coordinatorState["prior_terminal_status"] = $priorTerminalStatus
                $coordinatorState["persistence_phase"] = $failedPersistencePhase
                $coordinatorState["persistence_error"] = $persistenceFailure
                $correctionErrors = [System.Collections.Generic.List[string]]::new()
                if ($terminalAttemptPersisted) {
                    try {
                        Append-Attempt -Value ([ordered]@{
                            schema = $attemptSchema
                            record_kind = "TERMINAL_CORRECTION"
                            attempt_id = "$attemptId.persistence_failure"
                            corrects_attempt_id = $attemptId
                            coordinator_run_id = $runId
                            status = "RETRY_NEXT_INTERVAL"
                            prior_terminal_status = $priorTerminalStatus
                            reason = $failureReason
                            persistence_phase = $failedPersistencePhase
                            persistence_error = $persistenceFailure
                            started_at_utc = Get-UtcIso -Value $startedAt
                            finished_at_utc = Get-UtcIso -Value $correctionAt
                            evaluated_at_utc = Get-UtcIso -Value $now
                            due_tracks = @($terminalPayload.due_tracks)
                            track_outcomes = @($terminalPayload.track_outcomes)
                            pending_retry = $true
                            retained_claim_for_active_worker = $true
                        })
                    } catch {
                        $correctionErrors.Add("ledger: $($_.Exception.Message)")
                    }
                }
                try {
                    Write-JsonAtomic -Path $CoordinatorStatePath -Value $coordinatorState
                } catch {
                    $correctionErrors.Add("state: $($_.Exception.Message)")
                }
                if ($correctionErrors.Count -gt 0) {
                    $terminalPayload["durability_correction_error"] = $correctionErrors -join " | "
                }
            }
            $retainClaim = $true
        }
    }
}

$terminalPayload.coordinator_state_path = $CoordinatorStatePath
$terminalPayload.coordinator_attempts_path = $CoordinatorAttemptsPath
$terminalPayload.coordinator_claim_path = $CoordinatorClaimPath
Publish-Result -Payload $terminalPayload -ExitCode $terminalExitCode
