param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanHash,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-PowerSettingIndices {
    param(
        [Parameter(Mandatory = $true)][string]$Subgroup,
        [Parameter(Mandatory = $true)][string]$Setting,
        [switch]$IncludeHidden
    )
    $powercfg = Join-Path $env:SystemRoot "System32\powercfg.exe"
    $querySwitch = if ($IncludeHidden) { "/QH" } else { "/QUERY" }
    $raw = & $powercfg $querySwitch SCHEME_CURRENT $Subgroup $Setting 2>&1
    $exitCode = $LASTEXITCODE
    $text = $raw | Out-String
    if ($exitCode -ne 0) {
        throw "powercfg query failed for $Subgroup/$Setting with exit $exitCode`: $text"
    }
    $hexValues = @(
        [regex]::Matches($text, "0x[0-9a-fA-F]{8}") |
            ForEach-Object { $_.Value }
    )
    $minimumHexValues = if ($IncludeHidden) { 2 } else { 5 }
    if ($hexValues.Count -lt $minimumHexValues) {
        throw "powercfg output for $Subgroup/$Setting is incomplete."
    }
    $acValue = [Convert]::ToUInt32($hexValues[-2].Substring(2), 16)
    $dcValue = [Convert]::ToUInt32($hexValues[-1].Substring(2), 16)
    return [ordered]@{
        ac_value = $acValue
        dc_value = $dcValue
        ac_sec = $acValue
        dc_sec = $dcValue
    }
}

function Get-RebootPendingSnapshot {
    $errors = [System.Collections.Generic.List[string]]::new()
    $cbsPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
    $windowsUpdatePath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    $sessionManagerPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager"

    $cbsPending = $false
    $windowsUpdatePending = $false
    $pendingFileRenameCount = $null
    try {
        $cbsPending = [bool](Test-Path -LiteralPath $cbsPath -ErrorAction Stop)
    } catch {
        $errors.Add("cbs_reboot_pending_unavailable:$($_.Exception.GetType().Name)")
    }
    try {
        $windowsUpdatePending = [bool](
            Test-Path -LiteralPath $windowsUpdatePath -ErrorAction Stop
        )
    } catch {
        $errors.Add("windows_update_reboot_pending_unavailable:$($_.Exception.GetType().Name)")
    }
    try {
        $sessionManager = Get-ItemProperty `
            -LiteralPath $sessionManagerPath `
            -ErrorAction Stop
        $pendingProperty = $sessionManager.PSObject.Properties[
            "PendingFileRenameOperations"
        ]
        $pendingFileRenameCount = if ($pendingProperty) {
            @($pendingProperty.Value).Count
        } else { 0 }
    } catch {
        $errors.Add("pending_file_rename_unavailable:$($_.Exception.GetType().Name)")
    }

    return [ordered]@{
        available = $errors.Count -eq 0
        cbs_reboot_pending = $cbsPending
        windows_update_reboot_required = $windowsUpdatePending
        pending_file_rename_operations_count = $pendingFileRenameCount
        hard_reboot_pending = [bool]($cbsPending -or $windowsUpdatePending)
        errors = @($errors)
    }
}

function Get-SystemPowerSnapshot {
    if (-not ("DenseWsHostPowerStatus" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DenseWsHostPowerStatus {
    [StructLayout(LayoutKind.Sequential)]
    public struct SYSTEM_POWER_STATUS {
        public byte ACLineStatus;
        public byte BatteryFlag;
        public byte BatteryLifePercent;
        public byte SystemStatusFlag;
        public uint BatteryLifeTime;
        public uint BatteryFullLifeTime;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool GetSystemPowerStatus(out SYSTEM_POWER_STATUS status);
}
'@
    }
    $status = New-Object DenseWsHostPowerStatus+SYSTEM_POWER_STATUS
    if (-not [DenseWsHostPowerStatus]::GetSystemPowerStatus([ref]$status)) {
        throw "GetSystemPowerStatus failed."
    }
    return [ordered]@{
        ac_line_status = [int]$status.ACLineStatus
        ac_online = [int]$status.ACLineStatus -eq 1
        battery_flag = [int]$status.BatteryFlag
        battery_life_percent = [int]$status.BatteryLifePercent
        battery_life_time_sec = [uint32]$status.BatteryLifeTime
        system_status_flag = [int]$status.SystemStatusFlag
    }
}

function ConvertTo-InvariantDouble {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [double]::Parse(
        $Value.Replace(",", "."),
        [System.Globalization.CultureInfo]::InvariantCulture
    )
}

function Get-WindowsTimeSnapshot {
    $w32tm = Join-Path $env:SystemRoot "System32\w32tm.exe"
    $raw = & $w32tm /query /status /verbose 2>&1
    $exitCode = $LASTEXITCODE
    $text = $raw | Out-String
    if ($exitCode -ne 0) {
        return [ordered]@{
            available = $false
            exit_code = $exitCode
            phase_offset_sec = $null
            root_dispersion_sec = $null
            last_good_sync_age_sec = $null
            error = $text.Trim()
        }
    }

    $phaseMatch = [regex]::Match(
        $text,
        "(?im)^\s*(?:Phase Offset|Смещение фазы):\s*([+-]?[0-9.,]+)s\s*$"
    )
    $dispersionMatch = [regex]::Match(
        $text,
        "(?im)^\s*(?:Root Dispersion|Дисперсия корня):\s*([0-9.,]+)s\s*$"
    )
    $ageMatch = [regex]::Match(
        $text,
        "(?im)^\s*(?:Time since Last Good Sync Time|Время, прошедшее с момента последней удачной синхронизации):\s*([0-9.,]+)s\s*$"
    )
    $orderedSecondValues = @(
        [regex]::Matches(
            $text,
            "(?m):\s*([+-]?[0-9]+(?:[.,][0-9]+)?)s\s*$"
        ) | ForEach-Object {
            ConvertTo-InvariantDouble $_.Groups[1].Value
        }
    )
    $fallbackAvailable = $orderedSecondValues.Count -ge 5
    $phaseOffset = if ($phaseMatch.Success) {
        ConvertTo-InvariantDouble $phaseMatch.Groups[1].Value
    } elseif ($fallbackAvailable) {
        [double]$orderedSecondValues[2]
    } else { $null }
    $rootDispersion = if ($dispersionMatch.Success) {
        ConvertTo-InvariantDouble $dispersionMatch.Groups[1].Value
    } elseif ($fallbackAvailable) {
        [double]$orderedSecondValues[1]
    } else { $null }
    $lastGoodSyncAge = if ($ageMatch.Success) {
        ConvertTo-InvariantDouble $ageMatch.Groups[1].Value
    } elseif ($fallbackAvailable) {
        [double]$orderedSecondValues[4]
    } else { $null }
    return [ordered]@{
        available = $phaseOffset -ne $null
        exit_code = $exitCode
        parse_mode = if ($phaseMatch.Success) { "localized_label" } elseif ($fallbackAvailable) {
            "verbose_field_order_fallback"
        } else { "unavailable" }
        phase_offset_sec = $phaseOffset
        root_dispersion_sec = $rootDispersion
        last_good_sync_age_sec = $lastGoodSyncAge
        error = if ($phaseOffset -ne $null) { $null } else { "phase_offset_not_reported" }
    }
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$ExpectedPlanHash = $ExpectedPlanHash.ToLowerInvariant()
if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "PlanOnly file is missing: $PlanPath"
}
$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json -DateKind String
if ([string]$plan.plan_hash -ne $ExpectedPlanHash) {
    throw "PlanOnly hash mismatch."
}
if ([string]$plan.schema -ne "trading_mvp_dense_ws_campaign_planonly_v1") {
    throw "PlanOnly schema mismatch."
}

$campaignRoot = [System.IO.Path]::GetFullPath([string]$plan.outputs.campaign_root)
$driveRoot = [System.IO.Path]::GetPathRoot($campaignRoot)
$drive = [System.IO.DriveInfo]::new($driveRoot)
$hardOutputCapBytes = [long]$plan.resources.hard_output_cap_bytes
$requiredFreeBytes = [long]($hardOutputCapBytes * 2)
$power = Get-SystemPowerSnapshot
$standby = Get-PowerSettingIndices -Subgroup "SUB_SLEEP" -Setting "STANDBYIDLE"
$hibernate = Get-PowerSettingIndices -Subgroup "SUB_SLEEP" -Setting "HIBERNATEIDLE"
$diskIdle = Get-PowerSettingIndices -Subgroup "SUB_DISK" -Setting "DISKIDLE"
$lidAction = Get-PowerSettingIndices `
    -Subgroup "SUB_BUTTONS" `
    -Setting "LIDACTION" `
    -IncludeHidden
$rebootPending = Get-RebootPendingSnapshot
$windowsTime = Get-WindowsTimeSnapshot
$timezone = [System.TimeZoneInfo]::Local.Id

$blockers = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
if (-not [bool]$power.ac_online) {
    $blockers.Add("ac_power_offline")
}
if ([uint32]$standby.ac_sec -ne 0) {
    $blockers.Add("ac_sleep_enabled")
}
if ([uint32]$hibernate.ac_sec -ne 0) {
    $blockers.Add("ac_hibernate_enabled")
}
if ([uint32]$lidAction.ac_value -ne 0) {
    $blockers.Add("ac_lid_close_can_interrupt_run")
}
if (-not [bool]$rebootPending.available) {
    $blockers.Add("windows_reboot_status_unavailable")
} elseif ([bool]$rebootPending.hard_reboot_pending) {
    $blockers.Add("windows_reboot_pending")
}
if ($drive.AvailableFreeSpace -lt $requiredFreeBytes) {
    $blockers.Add("insufficient_disk_headroom")
}
if ($timezone -ne "Volgograd Standard Time") {
    $blockers.Add("unexpected_timezone")
}
if (-not [bool]$windowsTime.available) {
    $blockers.Add("windows_time_status_unavailable")
} elseif ([math]::Abs([double]$windowsTime.phase_offset_sec) -gt 0.5) {
    $blockers.Add("clock_phase_offset_above_500ms")
}
if ([uint32]$standby.dc_sec -ne 0) {
    $warnings.Add("battery_sleep_enabled")
}
if ([uint32]$lidAction.dc_value -ne 0) {
    $warnings.Add("battery_lid_close_can_interrupt_run")
}
if (
    $rebootPending.pending_file_rename_operations_count -ne $null -and
    [int]$rebootPending.pending_file_rename_operations_count -gt 0
) {
    $warnings.Add("pending_file_rename_operations_present")
}
if ([uint32]$diskIdle.ac_sec -ne 0) {
    $warnings.Add("disk_idle_timeout_enabled_but_continuous_writer_is_expected")
}
if (
    $windowsTime.last_good_sync_age_sec -ne $null -and
    [double]$windowsTime.last_good_sync_age_sec -gt 86400
) {
    $warnings.Add("last_good_time_sync_older_than_24h")
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_host_readiness_v1"
    status = if ($blockers.Count -eq 0) { "READY" } else { "BLOCKED" }
    no_run_or_output_writes = $true
    observed_at_local = [DateTimeOffset]::Now.ToString("o")
    campaign_id = [string]$plan.campaign_id
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = Get-Sha256 -Path $PlanPath
    campaign_root = $campaignRoot
    disk = [ordered]@{
        drive = $drive.Name
        available_free_bytes = [long]$drive.AvailableFreeSpace
        hard_output_cap_bytes = $hardOutputCapBytes
        required_free_bytes = $requiredFreeBytes
    }
    power = [ordered]@{
        system = $power
        standby_ac_sec = [uint32]$standby.ac_sec
        standby_dc_sec = [uint32]$standby.dc_sec
        hibernate_ac_sec = [uint32]$hibernate.ac_sec
        hibernate_dc_sec = [uint32]$hibernate.dc_sec
        disk_idle_ac_sec = [uint32]$diskIdle.ac_sec
        disk_idle_dc_sec = [uint32]$diskIdle.dc_sec
        lid_action_ac_index = [uint32]$lidAction.ac_value
        lid_action_dc_index = [uint32]$lidAction.dc_value
    }
    reboot_pending = $rebootPending
    time = [ordered]@{
        timezone = $timezone
        windows_time = $windowsTime
        max_abs_phase_offset_sec = 0.5
    }
    blockers = @($blockers)
    warnings = @($warnings)
    network_request_performed = $false
    system_setting_changed = $false
    writer_started = $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 20
} else {
    $result | Format-List
}
