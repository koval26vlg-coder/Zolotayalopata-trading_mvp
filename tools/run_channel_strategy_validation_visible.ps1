param(
    [ValidateSet('verify','sources','gate-history-audit','gate-catalog-audit','gate-survivorship-audit','gate-trades-audit','gate-metadata-audit','okx-history-audit','okx-full-archive','okx-archive-census','okx-dependencies','gold-history-audit','gold-history-remaining','histdata-sample','histdata-archive','histdata-local','archive-audit','inventory','validate','evaluate','report','pipeline')][string]$Stage = 'pipeline',
    [string]$InputManifest = '',
    [string]$EvaluationPath = '',
    [ValidateRange(1,1800)][int]$MaxRuntimeSec = 1800,
    [string]$RunId = '',
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Stop,
    [switch]$VisibleWorker,
    [string]$Token = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = 'C:\Program Files\Python313\python.exe'
$outRoot = Join-Path $root 'docs\analysis\channel-strategy-validation-20261006\runs'
$env:PYTHONPATH = Join-Path $root 'trading_mvp\src'
$env:PYTHONDONTWRITEBYTECODE = '1'
function Emit($value) { $value | ConvertTo-Json -Depth 20 }
function Read-Json($path) { Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -DateKind String }
function New-Json($path,$value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Depth 20))
    $temp = $path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $f = [IO.File]::Open($temp,'CreateNew','Write','None')
        try { $f.Write($bytes); $f.Flush($true) } finally { $f.Dispose() }
        [IO.File]::Move($temp,$path)
    } finally { if (Test-Path -LiteralPath $temp) { [IO.File]::Delete($temp) } }
}
function Quote([string]$value) {
    if ($value.Contains('"') -or $value.Contains("`n")) { throw 'Unsafe argument' }
    return '"' + $value + '"'
}
try {
    if (($Status -and $Stop) -or ($PreflightOnly -and ($Status -or $Stop -or $VisibleWorker))) { throw 'Conflicting actions' }
    if (-not $RunId) {
        if ($Status -or $Stop -or $VisibleWorker) { throw 'RunId required' }
        $RunId = 'history_' + $Stage + '_' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    }
    if ($RunId -notmatch '^history_[A-Za-z0-9_-]{1,100}$') { throw 'Invalid RunId' }
    $output = Join-Path $outRoot $RunId
    if ($Status -or $Stop) {
        if (-not (Test-Path -LiteralPath $output)) { Emit @{status='NOT_STARTED';run_id=$RunId}; exit 0 }
        if (Test-Path -LiteralPath (Join-Path $output 'completion.json')) { Emit (Read-Json (Join-Path $output 'completion.json')); exit 0 }
        if (-not (Test-Path -LiteralPath (Join-Path $output 'owner.json'))) { Emit @{status='UNKNOWN_LAUNCH_OUTCOME';run_id=$RunId;retry_authorized=$false}; exit 2 }
        $owner = Read-Json (Join-Path $output 'owner.json')
        $worker = Get-Process -Id $owner.worker_pid -ErrorAction SilentlyContinue
        if (-not $worker -or $worker.StartTime.ToUniversalTime().ToString('o') -ne $owner.worker_started_utc) {
            Emit @{status='STOPPED_INCOMPLETE';run_id=$RunId;retry_authorized=$false}; exit 2
        }
        if ($Stop -and -not (Test-Path -LiteralPath (Join-Path $output 'stop.json'))) {
            New-Json (Join-Path $output 'stop.json') @{requested_utc=[DateTime]::UtcNow.ToString('o')}
        }
        Emit @{status=$(if ($Stop) {'STOP_REQUESTED'} else {'RUNNING'});run_id=$RunId;worker_pid=$worker.Id;output=$output}; exit 0
    }
    $guardText = & (Join-Path $root 'tools\check_trading_mvp_autopilot.ps1') -Json
    if ($LASTEXITCODE -ne 0) { throw 'Guard failed' }
    $guard = ($guardText -join "`n") | ConvertFrom-Json -DateKind String
    if ($guard.usage.decision -ne 'CONTINUE' -or $guard.usage.remaining_percent -le 15 -or $guard.status -like 'PAUSED*') { throw 'Quota paused/unavailable' }
    $reads = @((Join-Path $root 'trading_mvp\src\channel_validation'), (Join-Path $root 'trading_mvp\tests\test_channel_validation.py'), (Join-Path $root 'docs\plans\channel-strategy-validation-20261006-v1.json'))
    if ($Stage -eq 'archive-audit') { $reads += 'E:\ZolotyayLopata-data\exports\trading-mvp' }
    if ($Stage -in @('gate-survivorship-audit','gate-trades-audit','gate-metadata-audit','okx-history-audit','okx-dependencies','gold-history-audit','histdata-sample') -and $MaxRuntimeSec -gt 300) { throw 'History source audit is bounded to 300 seconds' }
    if ($Stage -eq 'gold-history-remaining') {
        if ($MaxRuntimeSec -gt 240) { throw 'Remaining gold phase is bounded to 240 seconds' }
        $reads += (Join-Path $outRoot 'history_gold_source_v7_20261007')
    }
    if ($Stage -eq 'histdata-archive') {
        if ($MaxRuntimeSec -gt 240) { throw 'HistData archive phase bounded to 240 seconds' }
        $reads += (Join-Path $outRoot 'history_histdata_gold_v8_20261007')
    }
    if ($Stage -eq 'histdata-local') {
        if ($MaxRuntimeSec -gt 300) { throw 'Local census bounded to 300 seconds' }
        $reads += (Join-Path $outRoot 'history_histdata_archive_v8_20261007')
        if ($RunId -eq 'history_histdata_local_recovery_v8_20261007') { $reads += (Join-Path $outRoot 'history_histdata_local_v8_20261007') }
    }
    if ($Stage -eq 'okx-dependencies') { $reads += (Join-Path $root 'docs\analysis\channel-strategy-validation-20261006\continuation-v5') }
    if ($Stage -eq 'okx-full-archive') { $reads += (Join-Path $outRoot 'history_okx_option_source_v4_20261006') }
    if ($Stage -eq 'okx-archive-census') {
        $reads += (Join-Path $outRoot 'history_okx_option_source_v4_20261006')
        $reads += (Join-Path $outRoot 'history_okx_full_btc_v5_20261006')
    }
    if ($Stage -eq 'gate-trades-audit') { $reads += (Join-Path $outRoot 'history_gate_survivorship_v3_20261006') }
    if ($Stage -in @('gate-history-audit','gate-catalog-audit')) {
        $reads += (Join-Path $root 'docs\analysis\channel-strategy-validation-20261006\gate-source-audit.json')
        $reads += (Join-Path $outRoot 'history_sources_v1_20261006\artifacts\public-history-sample')
        if ($Stage -eq 'gate-catalog-audit') { $reads += (Join-Path $outRoot 'history_gate_units_v2_20261006') }
        if ($MaxRuntimeSec -gt 300) { throw 'History source audit is bounded to 300 seconds' }
    }
    if ($InputManifest) { $InputManifest = (Resolve-Path -LiteralPath $InputManifest).Path; $reads += (Split-Path $InputManifest) }
    if ($Stage -eq 'report' -and -not $EvaluationPath) { throw 'Report requires -EvaluationPath' }
    if ($EvaluationPath) { $EvaluationPath = (Resolve-Path -LiteralPath $EvaluationPath).Path; $reads += (Split-Path $EvaluationPath) }
    $gateText = & (Join-Path $root 'tools\check_active_run_gate.ps1') -OfflineWork -ReadResourcePath $reads -WriteResourcePath @($output) -Json
    if ($LASTEXITCODE -ne 0) { throw 'Scoped gate failed' }
    $gate = ($gateText -join "`n") | ConvertFrom-Json -DateKind String
    if (-not $gate.scope_decision.allowed -or $gate.gate_status -eq 'RUNNING') { throw 'Gate forbids a second run' }
    $checkText = & $python -m channel_validation.runner preflight
    if ($LASTEXITCODE -ne 0) { throw 'Plan preflight failed' }
    $check = ($checkText -join "`n") | ConvertFrom-Json -DateKind String
    $hashText = & $python -c 'from channel_validation.contract import *; print(canonical_hash(runtime_binding()))'
    if ($LASTEXITCODE -ne 0) { throw 'Runtime hash failed' }
    $runtimeHash = ($hashText -join '').Trim()
    if ($Stage -eq 'okx-full-archive') {
        if ($RunId -ne 'history_okx_full_btc_v5_20261006') { throw 'One-shot download RunId is fixed; no renamed retry' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'Download attempt already recorded; use Status or local census, not another network run' }
        & $python -c 'from channel_validation.okx_acquire import acquisition_plan; from channel_validation.contract import canonical_hash; p=acquisition_plan(); print(canonical_hash(p))' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Bound historical acquisition preflight failed' }
    }
    if ($Stage -eq 'okx-archive-census') {
        & $python -c 'from channel_validation.okx_acquire import local_census_plan; local_census_plan()' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Bound local archive preflight failed' }
    }
    if ($Stage -eq 'okx-dependencies') {
        if ($RunId -ne 'history_okx_dependencies_v6_20261007') { throw 'Dependency audit RunId is fixed; no renamed retry' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'Dependency audit already recorded; use Status' }
        & $python -c 'from channel_validation.okx_dependencies import preflight; preflight()' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Bound option dependency preflight failed' }
    }
    if ($Stage -eq 'gold-history-audit') {
        if ($RunId -ne 'history_gold_source_v7_20261007') { throw 'Gold source audit RunId is fixed; no renamed retry' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'Gold source audit already recorded; use Status' }
    }
    if ($Stage -eq 'gold-history-remaining') {
        if ($RunId -ne 'history_gold_unattempted_v7_20261007') { throw 'Unattempted gold phase RunId is fixed' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'Remaining gold phase already recorded; use Status' }
        & $python -c 'from channel_validation.gold_history import remaining_preflight; remaining_preflight()' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Exact failed parent provenance not established' }
    }
    if ($Stage -eq 'histdata-sample') {
        if ($RunId -ne 'history_histdata_gold_v8_20261007') { throw 'HistData RunId is fixed; no renamed retry' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'HistData already attempted; use Status' }
    }
    if ($Stage -eq 'histdata-archive') {
        if ($RunId -ne 'history_histdata_archive_v8_20261007') { throw 'HistData archive RunId fixed; no renamed retry' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'HistData archive already attempted' }
        & $python -c 'from channel_validation.histdata import cached_form_preflight; cached_form_preflight()' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Exact cached HistData page preflight failed' }
    }
    if ($Stage -eq 'histdata-local') {
        if ($RunId -notin @('history_histdata_local_v8_20261007','history_histdata_local_recovery_v8_20261007')) { throw 'Fixed local census RunId required' }
        if ($PreflightOnly -and (Test-Path -LiteralPath $output)) { throw 'Local census already attempted' }
        & $python -c 'from channel_validation.histdata_local import preflight,RECOVERY_RUN_ID; import sys; preflight(recovery=sys.argv[1]==RECOVERY_RUN_ID)' $RunId | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Local quarantined ZIP binding failed' }
    }
    if ($PreflightOnly) { Emit @{status=$(if($Stage -in @('sources','gate-history-audit','gate-catalog-audit','gate-survivorship-audit','gate-trades-audit','gate-metadata-audit','okx-history-audit','okx-full-archive','okx-dependencies','gold-history-audit','gold-history-remaining','histdata-sample','histdata-archive')){'READY_BOUNDED_PUBLIC_HISTORY'}else{'READY_OFFLINE_ONLY'});public_network_required=($Stage -in @('sources','gate-history-audit','gate-catalog-audit','gate-survivorship-audit','gate-trades-audit','gate-metadata-audit','okx-history-audit','okx-full-archive','okx-dependencies','gold-history-audit','gold-history-remaining','histdata-sample','histdata-archive'));runtime_hash=$runtimeHash;plan_hash=$check.plan_hash;output_created=$false;run_id=$RunId}; exit 0 }
    if (-not $VisibleWorker) {
        if (Test-Path -LiteralPath $output) { throw 'Namespace already used; no blind retry' }
        [IO.Directory]::CreateDirectory($output) | Out-Null
        $Token = [Guid]::NewGuid().ToString('N')
        New-Json (Join-Path $output 'intent.json') @{stage=$Stage;token=$Token;runtime_hash=$runtimeHash;runtime=$check.runtime;plan_hash=$check.plan_hash;input_manifest=$InputManifest;evaluation_path=$EvaluationPath;max_runtime_sec=$MaxRuntimeSec}
        $args = @('-NoProfile','-NoExit','-File',(Quote $PSCommandPath),'-VisibleWorker','-Stage',$Stage,'-RunId',$RunId,'-Token',$Token,'-MaxRuntimeSec',$MaxRuntimeSec)
        if ($InputManifest) { $args += @('-InputManifest',(Quote $InputManifest)) }
        if ($EvaluationPath) { $args += @('-EvaluationPath',(Quote $EvaluationPath)) }
        $terminal = Start-Process -FilePath (Get-Command pwsh).Source -ArgumentList $args -WorkingDirectory $root -WindowStyle Normal -PassThru
        New-Json (Join-Path $output 'dispatch.json') @{terminal_pid=$terminal.Id;terminal_started_utc=$terminal.StartTime.ToUniversalTime().ToString('o');token=$Token;handshake_timeout_sec=300}
        # The visible worker repeats fresh guards before claiming a writer.
        $until = [DateTime]::UtcNow.AddSeconds(300)
        do {
            if (Test-Path -LiteralPath (Join-Path $output 'launch-failure.json')) { throw 'Visible worker preflight failed; inspect launch-failure.json' }
            if (Test-Path -LiteralPath (Join-Path $output 'owner.json')) {
                $owner = Read-Json (Join-Path $output 'owner.json')
                if ($owner.token -ne $Token -or $owner.owner_pid -ne $terminal.Id -or -not $owner.job_assigned) { throw 'Ownership mismatch' }
                Emit @{status='VISIBLE_TERMINAL_LAUNCHED';run_id=$RunId;terminal_ownership_verified=$true;terminal_pid=$terminal.Id;writer_pid=$owner.worker_pid;output=$output}; exit 0
            }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $until -and -not $terminal.HasExited)
        throw 'Unknown launch outcome; inspect -Status, do not repeat'
    }
    $intent = Read-Json (Join-Path $output 'intent.json')
    if ($intent.token -ne $Token -or $intent.runtime_hash -ne $runtimeHash -or $intent.stage -ne $Stage -or $intent.max_runtime_sec -ne $MaxRuntimeSec -or $intent.input_manifest -ne $InputManifest -or $intent.evaluation_path -ne $EvaluationPath) { throw 'Exact dispatch mismatch' }
    if (Test-Path -LiteralPath (Join-Path $output 'owner.json')) { throw 'Already owned' }
    $env:TEMP = Join-Path $output 'temporary'
    $env:TMP = $env:TEMP
    [IO.Directory]::CreateDirectory($env:TEMP) | Out-Null
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HistoryJob {
    [StructLayout(LayoutKind.Sequential)] public struct Basic { public long ProcessTime,JobTime; public uint Flags; public UIntPtr Min,Max; public uint Active; public UIntPtr Affinity; public uint Priority,Scheduling; }
    [StructLayout(LayoutKind.Sequential)] public struct Counters { public ulong A,B,C,D,E,F; }
    [StructLayout(LayoutKind.Sequential)] public struct Extended { public Basic BasicInfo; public Counters IO; public UIntPtr ProcessMemory,JobMemory,PeakProcess,PeakJob; }
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] public static extern IntPtr CreateJobObject(IntPtr a,string n);
    [DllImport("kernel32.dll")] public static extern bool SetInformationJobObject(IntPtr j,int c,IntPtr p,uint n);
    [DllImport("kernel32.dll")] public static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
}
'@
    if (-not [HistoryJob]::IsWindowVisible([HistoryJob]::GetConsoleWindow())) { throw 'Visible console required' }
    $job = [HistoryJob]::CreateJobObject([IntPtr]::Zero,$null)
    if ($job -eq [IntPtr]::Zero) { throw 'Job creation failed' }
    $child = $null
    try {
        $info = [HistoryJob+Extended]::new(); $basic = [HistoryJob+Basic]::new(); $basic.Flags=0x2000; $info.BasicInfo=$basic
        $size = [Runtime.InteropServices.Marshal]::SizeOf($info); $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
        try {
            [Runtime.InteropServices.Marshal]::StructureToPtr($info,$buffer,$false)
            if (-not [HistoryJob]::SetInformationJobObject($job,9,$buffer,$size)) { throw 'Job limit failed' }
        } finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer) }
        Write-Host "Historical validation: $Stage; no private API/orders; MaxRuntimeSec=$MaxRuntimeSec"
        Write-Host "Status: & '$PSCommandPath' -Status -RunId '$RunId'"
        Write-Host "Stop: & '$PSCommandPath' -Stop -RunId '$RunId'"
        $child = Start-Process -FilePath $python -ArgumentList @('-u','-m','channel_validation.execution','--run-id',$RunId,'--token',$Token) -WorkingDirectory $root -NoNewWindow -PassThru
        if (-not [HistoryJob]::AssignProcessToJobObject($job,$child.Handle)) { throw 'Job assignment failed' }
        New-Json (Join-Path $output 'owner.json') @{owner_pid=$PID;worker_pid=$child.Id;worker_started_utc=$child.StartTime.ToUniversalTime().ToString('o');token=$Token;job_assigned=$true}
        $watch = [Diagnostics.Stopwatch]::StartNew(); $stopping=$null
        while (-not $child.WaitForExit(500)) {
            if (Test-Path -LiteralPath (Join-Path $output 'stop.json')) { if ($null -eq $stopping) {$stopping=$watch.Elapsed.TotalSeconds} }
            if ($watch.Elapsed.TotalSeconds -ge $MaxRuntimeSec -or ($null -ne $stopping -and $watch.Elapsed.TotalSeconds-$stopping -ge 5)) {
                Stop-Process -InputObject $child -Force
                throw 'STOPPED_INCOMPLETE: owned worker stopped; retain partial output and claim'
            }
        }
        if ($child.ExitCode -ne 0) { throw 'STOPPED_INCOMPLETE: inspect visible output' }
        Emit (Read-Json (Join-Path $output 'completion.json'))
    } finally {
        if ($null -ne $child -and -not $child.HasExited) { Stop-Process -InputObject $child -Force -ErrorAction SilentlyContinue }
        [HistoryJob]::CloseHandle($job) | Out-Null
    }
} catch {
    $failure = @{status='BLOCKED';run_id=$RunId;reason=$_.Exception.Message}
    if ($VisibleWorker -and $output -and (Test-Path -LiteralPath (Join-Path $output 'intent.json')) -and -not (Test-Path -LiteralPath (Join-Path $output 'owner.json'))) {
        $failedIntent = Read-Json (Join-Path $output 'intent.json')
        if ($Token -and $failedIntent.token -eq $Token -and -not (Test-Path -LiteralPath (Join-Path $output 'launch-failure.json'))) {
            New-Json (Join-Path $output 'launch-failure.json') $failure
        }
    }
    Emit $failure; exit 2
}
