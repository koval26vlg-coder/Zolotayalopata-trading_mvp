param([switch]$Status,[switch]$Stop,[switch]$Child,[string]$Token='')
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent) -Parent
$python='C:\Program Files\Python313\python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'
function ReadJson($p) { Get-Content -LiteralPath $p -Raw | ConvertFrom-Json -DateKind String }
function NewJson($name,$value) {
    $raw=[Text.Encoding]::UTF8.GetBytes(($value|ConvertTo-Json -Depth 12))
    $f=[IO.File]::Open((Join-Path $PSScriptRoot $name),'CreateNew','Write','None')
    try {$f.Write($raw);$f.Flush($true)} finally {$f.Dispose()}
}
if ($Status -or $Stop) {
    if(Test-Path "$PSScriptRoot/completion.json"){Get-Content "$PSScriptRoot/completion.json" -Raw;exit}
    if($Stop -and -not(Test-Path "$PSScriptRoot/stop.json")){NewJson 'stop.json' @{requested_utc=[DateTime]::UtcNow.ToString('o')}}
    if(Test-Path "$PSScriptRoot/owner.json"){
        $o=ReadJson "$PSScriptRoot/owner.json"
        $p=Get-Process -Id $o.worker_pid -ErrorAction SilentlyContinue
        $alive=$p -and $p.StartTime.ToUniversalTime().ToString('o') -eq $o.worker_started_utc
        @{status=$(if($alive){'RUNNING'}else{'STOPPED_INCOMPLETE'});retry_authorized=$false}|ConvertTo-Json
    }else{@{status='NO_VERIFIED_OWNER';retry_authorized=$false}|ConvertTo-Json}
    exit
}
$g=((& "$root/tools/check_trading_mvp_autopilot.ps1" -Json)-join "`n")|ConvertFrom-Json
if($LASTEXITCODE -ne 0 -or $g.usage.decision -ne 'CONTINUE' -or $g.usage.remaining_percent -le 15 -or $g.status -like 'PAUSED*'){throw 'Quota paused/unavailable'}
$reads=@("$root/trading_mvp/src/channel_validation",(Split-Path $PSScriptRoot -Parent),"$root/docs/plans/channel-strategy-validation-20261006-v1.json")
$gate=((& "$root/tools/check_active_run_gate.ps1" -OfflineWork -ReadResourcePath $reads -WriteResourcePath @($PSScriptRoot) -Json)-join "`n")|ConvertFrom-Json
if($LASTEXITCODE -ne 0 -or -not $gate.scope_decision.allowed -or $gate.gate_status -eq 'RUNNING'){throw 'Technical gate closed'}
& $python "$PSScriptRoot/audit_evidence.py" --preflight
if($LASTEXITCODE -ne 0){throw 'Audit bindings invalid'}
if(-not $Child){
    if(Test-Path "$PSScriptRoot/dispatch.json"){throw 'Already dispatched; use Status, do not duplicate owner'}
    $Token=[Guid]::NewGuid().ToString('N')
    $terminal=Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' -ArgumentList @('-NoProfile','-NoExit','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-Child','-Token',$Token) -WorkingDirectory $root -WindowStyle Normal -PassThru
    NewJson 'dispatch.json' @{token=$Token;terminal_pid=$terminal.Id;window_style='Normal';no_exit=$true;script_sha256=(Get-FileHash $PSCommandPath).Hash.ToLower()}
    $until=[DateTime]::UtcNow.AddSeconds(90)
    do {
        if(Test-Path "$PSScriptRoot/owner.json"){
            $o=ReadJson "$PSScriptRoot/owner.json"
            if($o.token -ne $Token -or $o.owner_pid -ne $terminal.Id -or -not $o.job_assigned){throw 'Ownership mismatch'}
            @{status='VISIBLE_TERMINAL_LAUNCHED';terminal_ownership_verified=$true;terminal_pid=$terminal.Id;worker_pid=$o.worker_pid;run_id='history_evidence_content_v22_20261009'}|ConvertTo-Json
            exit
        }
        Start-Sleep -Milliseconds 200
    }while([DateTime]::UtcNow -lt $until -and -not $terminal.HasExited)
    throw 'Unknown launch outcome; use Status, do not repeat'
}
$d=ReadJson "$PSScriptRoot/dispatch.json"
if($d.token -ne $Token -or $d.terminal_pid -ne $PID -or (Test-Path "$PSScriptRoot/owner.json")){throw 'Invalid/already owned dispatch'}
# Reuse the byte-bound, tested job-object definition without changing its launcher.
$source=Get-Content "$root/tools/run_channel_strategy_validation_visible.ps1" -Raw
$match=[regex]::Match($source,"(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@")
if(-not $match.Success){throw 'Visible-owner job definition unavailable'}
Add-Type -TypeDefinition $match.Groups[1].Value
if(-not [HistoryJob]::IsWindowVisible([HistoryJob]::GetConsoleWindow())){throw 'Visible console required'}
$job=[HistoryJob]::CreateJobObject([IntPtr]::Zero,$null)
if($job -eq [IntPtr]::Zero){throw 'Job creation failed'}
$worker=$null
try {
    $info=[HistoryJob+Extended]::new();$basic=[HistoryJob+Basic]::new();$basic.Flags=0x2000;$info.BasicInfo=$basic
    $size=[Runtime.InteropServices.Marshal]::SizeOf($info);$buffer=[Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    try {
        [Runtime.InteropServices.Marshal]::StructureToPtr($info,$buffer,$false)
        if(-not [HistoryJob]::SetInformationJobObject($job,9,$buffer,$size)){throw 'Job limit failed'}
    }finally{[Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)}
    Write-Host 'Evidence content audit: local metadata only; no network/market replay; maximum 120 seconds.'
    Write-Host "Status: & '$PSCommandPath' -Status"
    Write-Host "Stop: & '$PSCommandPath' -Stop"
    $worker=Start-Process -FilePath $python -ArgumentList @('-u',('"'+"$PSScriptRoot/audit_evidence.py"+'"'),'--token',$Token) -WorkingDirectory $root -NoNewWindow -PassThru
    if(-not [HistoryJob]::AssignProcessToJobObject($job,$worker.Handle)){throw 'Job assignment failed'}
    NewJson 'owner.json' @{worker_pid=$worker.Id;worker_started_utc=$worker.StartTime.ToUniversalTime().ToString('o');owner_pid=$PID;token=$Token;job_assigned=$true}
    if(-not $worker.WaitForExit(120000)){$worker.Kill($true);throw 'Audit runtime exceeded'}
    if($worker.ExitCode -ne 0){throw 'STOPPED_INCOMPLETE: inspect terminal; do not retry'}
    Get-Content "$PSScriptRoot/completion.json" -Raw
}finally{
    if($worker -and -not $worker.HasExited){$worker.Kill($true)}
    [HistoryJob]::CloseHandle($job)|Out-Null
}
