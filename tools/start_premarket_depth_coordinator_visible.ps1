param(
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Stop,
    [switch]$VisibleWorker,
    [string]$RunId = '',
    [string]$RuntimeManifestPath = '',
    [string]$LaunchToken = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = 'C:\Program Files\Python313\python.exe'
$module = Join-Path $root 'trading_mvp\src\premarket_depth_coordinator.py'
if (-not $RuntimeManifestPath) {
    $RuntimeManifestPath = Join-Path $root 'docs\plans\premarket-depth-coordinator-runtime-20261006-v1.json'
}
function Emit($value) { $value | ConvertTo-Json -Depth 12 }
function Read-Json($path) { Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -DateKind String }
function Create-Json($path, $value) {
    $data = [Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Depth 12))
    $temp = $path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $f = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $f.Write($data, 0, $data.Length); $f.Flush($true) } finally { $f.Dispose() }
        # Publish the whole owner record at once, without replacing another owner.
        [IO.File]::Move($temp, $path)
    } finally {
        if (Test-Path -LiteralPath $temp) { [IO.File]::Delete($temp) }
    }
}
function Quote-Arg([string]$value) {
    if ($value.Contains('"') -or $value.Contains("`n")) { throw 'Unsafe command argument' }
    return '"' + $value + '"'
}
function Control-Path([string]$id) {
    if ($id -notmatch '^premarket_depth_[A-Za-z0-9_-]{1,100}$') { throw 'Exact run_id required' }
    return Join-Path $root "docs\agent-log\run-gates\$id.depth-owner.json"
}
function New-OwnerJob {
    $job = [PremarketDepthJob]::CreateJobObject([IntPtr]::Zero, $null)
    if ($job -eq [IntPtr]::Zero) { throw 'Cannot create owner Job Object' }
    try {
        $info = [PremarketDepthJob+Extended]::new()
        # PowerShell mutates a copy of nested value types; assign the entire Basic.
        $basic = [PremarketDepthJob+Basic]::new()
        $basic.Flags = 0x2000 # KILL_ON_JOB_CLOSE
        $info.BasicInfo = $basic
        if ($info.BasicInfo.Flags -ne 0x2000) { throw 'Kill-on-close flag missing' }
        $size = [Runtime.InteropServices.Marshal]::SizeOf($info)
        $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
        try {
            [Runtime.InteropServices.Marshal]::StructureToPtr($info, $buffer, $false)
            if (-not [PremarketDepthJob]::SetInformationJobObject($job, 9, $buffer, $size)) { throw 'Cannot set kill-on-close' }
        } finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer) }
        return $job
    } catch {
        [PremarketDepthJob]::CloseHandle($job) | Out-Null
        throw
    }
}

try {
    if (($Status -and $Stop) -or ($PreflightOnly -and ($Status -or $Stop -or $VisibleWorker))) { throw 'Conflicting actions' }
    if ($Status -or $Stop) {
        $control = Control-Path $RunId
        if (-not (Test-Path -LiteralPath $control)) { Emit @{status='NOT_STARTED';run_id=$RunId}; exit 0 }
        $owner = Read-Json $control
        $out = Join-Path $root "docs\analysis\premarket-depth-coordinator-runs\$RunId"
        if ($owner.run_id -ne $RunId -or $owner.output -ne $out) { throw 'Owner record mismatch' }
        $resultPath = Join-Path $out 'result.json'
        if (Test-Path -LiteralPath $resultPath) { Emit (Read-Json $resultPath); exit 0 }
        $worker = Get-Process -Id $owner.worker_pid -ErrorAction SilentlyContinue
        if (-not $worker -or $worker.StartTime.ToUniversalTime().ToString('o') -ne $owner.worker_started_utc) {
            Emit @{status='STOPPED_INCOMPLETE';run_id=$RunId;reason='Writer absent; preserve claim and partial files';retry_authorized=$false}; exit 2
        }
        if ($Stop) {
            $stopFile = [IO.Path]::ChangeExtension($control, '.stop')
            if (-not (Test-Path -LiteralPath $stopFile)) { Create-Json $stopFile @{requested_utc=[DateTime]::UtcNow.ToString('o')} }
            Emit @{status='STOP_REQUESTED';run_id=$RunId}; exit 0
        }
        $files = @(Get-ChildItem -LiteralPath $out -File -ErrorAction SilentlyContinue)
        Emit @{status='RUNNING';run_id=$RunId;writer_pid=$worker.Id;bytes=($files | Measure-Object Length -Sum).Sum;output=$out}; exit 0
    }

    $guardText = & (Join-Path $root 'tools\check_trading_mvp_autopilot.ps1') -Json
    if ($LASTEXITCODE -ne 0) { throw 'Autopilot guard failed' }
    $guard = ($guardText -join "`n") | ConvertFrom-Json -DateKind String
    $gateText = & (Join-Path $root 'tools\check_active_run_gate.ps1') -Json
    if ($LASTEXITCODE -ne 0) { throw 'Active gate failed' }
    $gate = ($gateText -join "`n") | ConvertFrom-Json -DateKind String
    if ($gate.gate_status -ne 'READY_FOR_POSTPROCESS' -or $guard.usage.decision -ne 'CONTINUE' -or $guard.usage.remaining_percent -le 15) { throw 'Technical gate/quota blocked' }
    $checkText = & $python $module --repo-root $root --manifest $RuntimeManifestPath --preflight
    $code = $LASTEXITCODE
    $check = ($checkText -join "`n") | ConvertFrom-Json -DateKind String
    if ($code -ne 0 -or $check.status -ne 'READY' -or $PreflightOnly) { Emit $check; exit $code }
    if ($RunId -and $RunId -ne $check.run_id) { throw 'Run identity mismatch' }
    $RunId = $check.run_id
    $control = Control-Path $RunId
    $intent = $control + '.intent'

    if (-not $VisibleWorker) {
        $LaunchToken = [Guid]::NewGuid().ToString('N')
        Create-Json $intent @{run_id=$RunId;token=$LaunchToken;runtime_manifest_hash=$check.runtime_manifest_hash;created_utc=[DateTime]::UtcNow.ToString('o')}
        $args = @('-NoProfile','-NoExit','-File',(Quote-Arg $PSCommandPath),'-VisibleWorker',
                  '-RunId',(Quote-Arg $RunId),'-RuntimeManifestPath',(Quote-Arg $RuntimeManifestPath),'-LaunchToken',$LaunchToken)
        $terminal = Start-Process -FilePath (Get-Command pwsh).Source -ArgumentList $args -WorkingDirectory $root -WindowStyle Normal -PassThru
        $until = [DateTime]::UtcNow.AddSeconds(60)
        do {
            if (Test-Path -LiteralPath $control) {
                $owner = Read-Json $control
                if ($owner.token -ne $LaunchToken -or $owner.owner_pid -ne $terminal.Id -or -not $owner.job_assigned) { throw 'Visible ownership mismatch' }
                Emit @{status='VISIBLE_TERMINAL_LAUNCHED';run_id=$RunId;terminal_pid=$terminal.Id;writer_pid=$owner.worker_pid;terminal_ownership_verified=$true}; exit 0
            }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $until -and -not $terminal.HasExited)
        throw 'Launch outcome uncertain; inspect -Status, do not retry'
    }

    $dispatch = Read-Json $intent
    if ($LaunchToken -notmatch '^[0-9a-f]{32}$' -or $dispatch.token -ne $LaunchToken -or $dispatch.runtime_manifest_hash -ne $check.runtime_manifest_hash) { throw 'Dispatch binding mismatch' }
    if (Test-Path -LiteralPath $control) { throw 'Worker already dispatched; no retry' }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PremarketDepthJob {
    [StructLayout(LayoutKind.Sequential)] public struct Basic {
        public long ProcessTime, JobTime; public uint Flags;
        public UIntPtr MinWorking, MaxWorking; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] public struct Counters { public ulong A,B,C,D,E,F; }
    [StructLayout(LayoutKind.Sequential)] public struct Extended {
        public Basic BasicInfo; public Counters IO; public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob;
    }
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr CreateJobObject(IntPtr a, string n);
    [DllImport("kernel32.dll")] public static extern bool SetInformationJobObject(IntPtr j,int c,IntPtr p,uint n);
    [DllImport("kernel32.dll")] public static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
}
'@
    if (-not [PremarketDepthJob]::IsWindowVisible([PremarketDepthJob]::GetConsoleWindow())) { throw 'Visible console required' }
    $job = New-OwnerJob
    $child = $null
    try {
        Write-Host "One public writer. Run: $RunId. MaxRuntimeSec=$($check.max_runtime_sec)"
        Write-Host "Status: & '$PSCommandPath' -Status -RunId '$RunId'"
        Write-Host "Stop: & '$PSCommandPath' -Stop -RunId '$RunId'"
        $args = @((Quote-Arg $module),'--repo-root',(Quote-Arg $root),'--manifest',(Quote-Arg $RuntimeManifestPath),'--run','--launch-token',$LaunchToken)
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $child = Start-Process -FilePath $python -ArgumentList $args -NoNewWindow -WorkingDirectory $root -PassThru
        if (-not [PremarketDepthJob]::AssignProcessToJobObject($job, $child.Handle)) { throw 'Cannot bind worker to visible owner' }
        Create-Json $control @{run_id=$RunId;token=$LaunchToken;owner_pid=$PID;worker_pid=$child.Id;
            worker_started_utc=$child.StartTime.ToUniversalTime().ToString('o');job_assigned=$true;
            runtime_manifest_hash=$check.runtime_manifest_hash;output=$check.output}
        $stopping = $null
        while (-not $child.WaitForExit(500)) {
            if (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($control, '.stop'))) {
                if ($null -eq $stopping) { $stopping = $watch.Elapsed.TotalSeconds }
            }
            if ($watch.Elapsed.TotalSeconds -ge $check.max_runtime_sec + 5 -or
                ($null -ne $stopping -and $watch.Elapsed.TotalSeconds - $stopping -ge 25)) {
                Stop-Process -InputObject $child -Force
                throw 'STOPPED_INCOMPLETE: watchdog stopped owned writer; preserve partial data and claim'
            }
        }
        if ($child.ExitCode -ne 0) { throw 'STOPPED_INCOMPLETE: inspect worker output; no automatic retry' }
        Emit @{status='WORKER_FINISHED';run_id=$RunId}
    } finally {
        if ($null -ne $child -and -not $child.HasExited) { Stop-Process -InputObject $child -Force -ErrorAction SilentlyContinue }
        [PremarketDepthJob]::CloseHandle($job) | Out-Null
    }
} catch {
    Emit @{status='BLOCKED';reason=$_.Exception.Message;run_id=$RunId}
    exit 2
}
