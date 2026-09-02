<#
.SYNOPSIS
Register the timer that watches for a scheduled spot listing and starts a depth capture.

.DESCRIPTION
The scan itself is one bounded pass over public venue metadata. It writes an armed-events
file and, when a capture window opens, starts a detached recorder that lives about four
hours. Nothing here places orders, authenticates, or spends anything.

The cadence follows from one requirement: an event has to be seen at least window_before -
two hours - before it opens, or the control window comes out short. With a scan interval I
and a venue notice N, worst-case detection is at N minus I, so I must stay under N minus 120.

OKX is measured and generous: a pending instrument has been seen at least 7h46m ahead, which
allows an interval of nearly six hours. Gate is unmeasured, and the first cadence chosen for
it was three minutes out of caution. That cost 2.0 GB a day - 4.16 MB per scan, twenty scans
an hour - to catch roughly seven qualifying events a month, and bought nothing over fifteen
minutes unless Gate's notice happens to land in a narrow band near two hours.

So: fifteen minutes, the scan asks for gzip (4.16 MB becomes 1.38 MB; three of the four
endpoints honour it), and the watcher now records when each scheduled event was first seen.
That makes the notice a measurement instead of a guess, and the cadence can be set from it
once a few Gate events have gone by.

Registration goes through schtasks with a task definition in XML rather than through
Register-ScheduledTask. That is not a stylistic choice: Register-ScheduledTask refused with
"access denied" for this task while schtasks created an equivalent one unelevated in the same
session, so the cmdlet was asking for rights the task does not need. The XML says exactly what
is registered, which is worth more here than the cmdlet's convenience.

The interpreter is pinned by absolute path. An unqualified name would be resolved against
PATH, which is CWE-426.

.PARAMETER DryRun
Print the task XML that would be registered, and register nothing.

.PARAMETER Uninstall
Remove the task. The armed-events file and any captures are left alone.
#>
param(
    [string]$TaskName = "ZolotyayLopata Premarket Forward Depth Scan",
    [string]$Python = "C:\Program Files\Python313\python.exe",
    [string]$RepoRoot = "C:\Users\koval\Documents\ZolotyayLopata",
    [ValidateRange(1, 60)][int]$IntervalMinutes = 15,
    [switch]$DryRun,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

function Emit {
    param([string]$Status, [hashtable]$Extra = @{})
    $payload = [ordered]@{ status = $Status; task = $TaskName }
    foreach ($e in $Extra.GetEnumerator()) { $payload[$e.Key] = $e.Value }
    $payload | ConvertTo-Json -Depth 12
}

if ($Uninstall) {
    schtasks /query /TN $TaskName *> $null
    if ($LASTEXITCODE -ne 0) { Emit "NOT_INSTALLED"; exit 0 }
    if ($DryRun) { Emit "WOULD_UNREGISTER"; exit 0 }
    $out = schtasks /delete /TN $TaskName /F 2>&1
    if ($LASTEXITCODE -ne 0) {
        Emit "BLOCKED" @{ reason = "delete failed"; detail = ($out | Out-String).Trim() }
        exit 2
    }
    Emit "UNREGISTERED" @{ captures_kept = $true }
    exit 0
}

$src = Join-Path $RepoRoot "trading_mvp\src"
$watcher = Join-Path $src "premarket_forward_depth_watch.py"
$planner = Join-Path $src "premarket_forward_depth_plan.py"

foreach ($path in @($Python, $watcher, $planner)) {
    if (-not (Test-Path -LiteralPath $path)) {
        Emit "BLOCKED" @{ reason = "missing: $path" }
        exit 2
    }
}

# The plan binds both modules by sha256. Registering a timer against code the plan does not
# cover would mean the first thing the scheduler ever ran was something nobody approved.
$check = & $Python $planner --plan-check 2>&1
if ($LASTEXITCODE -ne 0) {
    Emit "BLOCKED" @{ reason = "plan check failed"; detail = ($check | Out-String).Trim() }
    exit 2
}

$hashes = @{}
foreach ($path in @($watcher, $planner)) {
    $hashes[[IO.Path]::GetFileName($path)] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$user = "{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME
$argument = '"{0}" --scan' -f $watcher
$esc = { param($s) [Security.SecurityElement]::Escape($s) }

# StartBoundary in the past with an interval and no duration: the repetition is open-ended,
# and StartWhenAvailable makes the scheduler catch up a run it slept through. A duration of
# TimeSpan::MaxValue is what the cmdlet path tried to serialise, and the scheduler rejected
# P99999999D as out of range.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Watches OKX and Gate for a scheduled spot listing whose perpetual already trades, and records the order book across it. Research only, public endpoints, no orders, no authentication.</Description>
    <URI>\$(& $esc $TaskName)</URI>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT${IntervalMinutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-09-02T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$(& $esc $user)</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$(& $esc $Python)</Command>
      <Arguments>$(& $esc $argument)</Arguments>
      <WorkingDirectory>$(& $esc $src)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

if ($DryRun) {
    Emit "WOULD_REGISTER" @{
        execute = $Python
        argument = $argument
        working_directory = $src
        interval_minutes = $IntervalMinutes
        principal = $user
        plan_check = "PLAN_OK"
        sha256 = $hashes
        registration_attempted = $false
    }
    Write-Output "--- task xml ---"
    Write-Output $xml
    exit 0
}

$xmlPath = Join-Path ([IO.Path]::GetTempPath()) ("zl-forward-depth-{0}.xml" -f ([guid]::NewGuid()))
try {
    # UTF-16 with a BOM, because the declaration says encoding="UTF-16" and schtasks believes it.
    [IO.File]::WriteAllText($xmlPath, $xml, [Text.UnicodeEncoding]::new($false, $true))
    $out = schtasks /create /TN $TaskName /XML $xmlPath /F 2>&1
    if ($LASTEXITCODE -ne 0) {
        Emit "BLOCKED" @{ reason = "schtasks refused"; detail = ($out | Out-String).Trim() }
        exit 2
    }
} finally {
    Remove-Item -LiteralPath $xmlPath -ErrorAction SilentlyContinue
}

$info = schtasks /query /TN $TaskName /FO LIST 2>&1 | Out-String
Emit "REGISTERED" @{
    interval_minutes = $IntervalMinutes
    execute = $Python
    argument = $argument
    principal = $user
    sha256 = $hashes
    uninstall = "pwsh -NoProfile -File `"$PSCommandPath`" -Uninstall"
    registration_attempted = $true
    query = ($info.Trim() -split "`r?`n" | Where-Object { $_ -match '^(TaskName|Status|Next Run Time|Следующий|Состояние|Имя задачи)' }) -join " | "
}
