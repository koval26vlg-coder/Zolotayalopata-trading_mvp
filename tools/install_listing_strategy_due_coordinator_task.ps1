param(
    [string]$TaskName = "ZolotyayLopata Listing Strategy Due Coordinator",
    [string]$CoordinatorPath = "",
    [string]$CodexAutomationsRoot = "",
    [ValidateRange(1, 86400)][int]$WorkerExitTimeoutSec = 1800,
    [switch]$DryRun,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $CoordinatorPath) {
    $CoordinatorPath = Join-Path $PSScriptRoot "invoke_listing_strategy_due_coordinator.ps1"
}
$CoordinatorPath = [IO.Path]::GetFullPath($CoordinatorPath)
if (-not (Test-Path -LiteralPath $CoordinatorPath -PathType Leaf)) {
    throw "coordinator not found: $CoordinatorPath"
}

if (-not $CodexAutomationsRoot) {
    $userProfilePath = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if (-not $userProfilePath) { throw "Windows user profile path is unavailable" }
    $CodexAutomationsRoot = Join-Path $userProfilePath ".codex\automations"
}
$CodexAutomationsRoot = [IO.Path]::GetFullPath($CodexAutomationsRoot)
$legacyAutomationIds = @(
    "zolotyaylopata-listing-momentum-monitor",
    "zolotyaylopata-pre-market-perpetual-listing-impulse-monitor",
    "zolotyaylopata-pre-ipo-perpetual-event-monitor"
)
$legacyRecords = [System.Collections.Generic.List[object]]::new()
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
        $legacyRecords.Add([pscustomobject]$record)
        continue
    }
    try {
        $bytes = [IO.File]::ReadAllBytes($automationPath)
        $text = $strictUtf8.GetString($bytes)
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $record.config_sha256 = [Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }
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
    $legacyRecords.Add([pscustomobject]$record)
}

if ($validationErrors.Count -gt 0) {
    [ordered]@{
        status = "BLOCKED_LEGACY_AUTOMATIONS"
        reason = "LEGACY_AUTOMATION_TOPOLOGY_INVALID"
        task_name = $TaskName
        coordinator_path = $CoordinatorPath
        codex_automations_root = $CodexAutomationsRoot
        registration_attempted = $false
        legacy_automations = @($legacyRecords)
        validation_errors = @($validationErrors)
    } | ConvertTo-Json -Depth 20
    exit 2
}

$actionArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$CoordinatorPath`" -ScheduledTick -Json -WorkerExitTimeoutSec $WorkerExitTimeoutSec -CodexAutomationsRoot `"$CodexAutomationsRoot`""

if ($DryRun) {
    [ordered]@{
        status = "READY_TO_INSTALL"
        task_name = $TaskName
        coordinator_path = $CoordinatorPath
        codex_automations_root = $CodexAutomationsRoot
        wake_interval_minutes = 5
        hidden = $true
        model_invocation = $false
        worker_exit_timeout_sec = $WorkerExitTimeoutSec
        action_arguments = $actionArguments
        registration_attempted = $false
        legacy_automations = @($legacyRecords)
    } | ConvertTo-Json -Depth 20
    exit 0
}

$pwsh = (Get-Command "pwsh.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $pwsh) { $pwsh = "C:\Program Files\PowerShell\7\pwsh.exe" }
if (-not (Test-Path -LiteralPath $pwsh -PathType Leaf)) {
    throw "pwsh.exe not found"
}

$action = New-ScheduledTaskAction -Execute $pwsh -Argument $actionArguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval ([TimeSpan]::FromMinutes(5)) -RepetitionDuration ([TimeSpan]::FromDays(3650))
$settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromHours(12)) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$payload = [ordered]@{
    status = "INSTALLED"
    task_name = $TaskName
    task_path = $registered.TaskPath
    coordinator_path = $CoordinatorPath
    wake_interval_minutes = 5
    hidden = $true
    model_invocation = $false
    worker_exit_timeout_sec = $WorkerExitTimeoutSec
    action_execute = $pwsh
    action_arguments = $actionArguments
    registration_attempted = $true
    legacy_automations = @($legacyRecords)
}
$payload | ConvertTo-Json -Depth 10
