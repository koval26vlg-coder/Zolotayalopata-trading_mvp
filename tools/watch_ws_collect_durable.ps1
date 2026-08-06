# Наблюдатель durable WS collect: только читает state.json; закрытие окна безвредно.
param(
    [Parameter(Mandatory = $true)][string]$RunDir,
    [int]$IntervalSec = 10,
    [int]$StaleAfterSec = 90
)

$stateFile = Join-Path $RunDir "state.json"
$launchFile = Join-Path $RunDir "launch.json"
$alertFile = Join-Path $RunDir "STOPPED_INCOMPLETE.txt"
$launch = $null
if (Test-Path -LiteralPath $launchFile) {
    try {
        $launch = Get-Content -Raw -LiteralPath $launchFile | ConvertFrom-Json
    } catch {
        $launch = $null
    }
}
$resumeCommand = if ($launch -and $launch.resume_command) {
    [string]$launch.resume_command
} else {
    $runId = Split-Path -Leaf $RunDir
    $starter = Join-Path $PSScriptRoot "start_ws_collect_durable.ps1"
    "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$starter`" -RunId `"$runId`" -Resume -ConfirmedLongRun"
}
Write-Host "Watching $stateFile (Ctrl+C / закрытие окна не влияет на сбор)"
Write-Host "Resume command: $resumeCommand"
while ($true) {
    if (-not (Test-Path $stateFile)) {
        Write-Host "[$(Get-Date -Format HH:mm:ss)] state.json еще не создан..."
        Start-Sleep -Seconds $IntervalSec
        continue
    }
    try {
        $state = Get-Content $stateFile -Raw | ConvertFrom-Json
    } catch {
        Start-Sleep -Seconds 2
        continue
    }
    $hbAge = [math]::Round(((Get-Date) - [DateTimeOffset]::FromUnixTimeMilliseconds([long]($state.heartbeat_epoch * 1000)).LocalDateTime).TotalSeconds, 0)
    $rawMb = [math]::Round((($state.raw_snapshot | Measure-Object -Property size_bytes -Sum).Sum) / 1MB, 1)
    $hbFlag = if ($hbAge -gt $StaleAfterSec -and $state.status -eq "running") { " !!! HEARTBEAT STALE (collector, вероятно, мертв)" } else { "" }
    Write-Host ("[{0}] status={1} seg={2}/{3} elapsed={4}s raw={5}MB hb_age={6}s errors={7}{8}" -f `
        (Get-Date -Format HH:mm:ss), $state.status, $state.segment_index, $state.segments_planned, `
        $state.elapsed_sec, $rawMb, $hbAge, $state.errors.Count, $hbFlag)
    if ($hbFlag) {
        Write-Host "Collector heartbeat is stale. If it does not recover, continue from console with:" -ForegroundColor Yellow
        Write-Host "  $resumeCommand" -ForegroundColor Yellow
    }
    if (Test-Path -LiteralPath $alertFile) {
        Write-Host "--- STOPPED alert ---" -ForegroundColor Yellow
        Get-Content -LiteralPath $alertFile -Tail 20
        Write-Host "--- end STOPPED alert ---" -ForegroundColor Yellow
    }
    if ($state.status -in @("completed", "failed", "terminated")) {
        Write-Host "=== FINAL: status=$($state.status) exit_reason=$($state.exit_reason) ==="
        Write-Host "Stitched manifest: $($state.stitched_manifest)"
        if ($state.status -ne "completed") {
            Write-Host "Continue from console:" -ForegroundColor Yellow
            Write-Host "  $resumeCommand" -ForegroundColor Yellow
        }
        break
    }
    Start-Sleep -Seconds $IntervalSec
}
