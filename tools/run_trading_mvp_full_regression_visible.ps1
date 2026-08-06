param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 10800)][int]$MaxRuntimeSec = 1200,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = 'C:\Program Files\Python313\python.exe'
$LogDirectory = Join-Path $RepoRoot 'exports\trading-mvp\run'
$LogPath = Join-Path $LogDirectory "$RunId.full-regression.visible.log"
$TempRoot = Join-Path $RepoRoot ".test-tmp\$RunId"
New-Item -ItemType Directory -Force -Path $LogDirectory, $TempRoot | Out-Null
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
# Keep Python and every nested Windows PowerShell process on one encoding.
# Otherwise localized JSON/diagnostics can be emitted as OEM bytes and kill a
# subprocess reader thread running in Python UTF-8 mode.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$started = Get-Date
"[$($started.ToString('o'))] full regression start run_id=$RunId max_runtime_sec=$MaxRuntimeSec" |
    Tee-Object -FilePath $LogPath

$job = Start-Job -ScriptBlock {
    param($PythonPath, $WorkingDirectory, $TemporaryRoot)
    Set-Location -LiteralPath $WorkingDirectory
    $env:TEMP = $TemporaryRoot
    $env:TMP = $TemporaryRoot
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    & $PythonPath -u -m unittest discover -s trading_mvp/tests 2>&1
    Write-Output "__TRADING_MVP_TEST_EXIT_CODE__=$LASTEXITCODE"
} -ArgumentList $Python, $RepoRoot, $TempRoot

$timedOut = $false
$childExitCode = $null
function Receive-TestOutput {
    param([Parameter(Mandatory = $true)]$TestJob)
    foreach ($item in @(Receive-Job -Job $TestJob 2>&1)) {
        $line = [string]$item
        if ($line -match '^__TRADING_MVP_TEST_EXIT_CODE__=(\d+)$') {
            $script:childExitCode = [int]$Matches[1]
            continue
        }
        $line | Tee-Object -FilePath $LogPath -Append
    }
}
while ($job.State -in @('NotStarted', 'Running')) {
    Receive-TestOutput -TestJob $job
    $elapsed = ((Get-Date) - $started).TotalSeconds
    Write-Host ("[regression-monitor] elapsed_sec={0:N0} state={1}" -f $elapsed, $job.State)
    if ($elapsed -ge $MaxRuntimeSec) {
        $timedOut = $true
        Stop-Job -Job $job
        break
    }
    Start-Sleep -Seconds 5
}
Receive-TestOutput -TestJob $job
$exitCode = if ($timedOut) { 124 } elseif ($null -ne $childExitCode) { $childExitCode } else { 1 }
Remove-Job -Job $job -Force

"[$((Get-Date).ToString('o'))] full regression exit_code=$exitCode timed_out=$timedOut" |
    Tee-Object -FilePath $LogPath -Append
if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit $exitCode
