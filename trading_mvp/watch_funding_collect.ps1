param(
    [string]$InputPath = "",
    [string]$ManifestPath = "",
    [string]$ProcessIds = "",
    [int]$RefreshSec = 30,
    [double]$StaleAfterSec = 900.0,
    [switch]$WatchOnce,
    [switch]$NoClear,
    [switch]$AutoResume,
    [string]$ResumeCommand = "",
    [string]$SnapshotPath = "",
    [int]$ProgressWidth = 42
)

$ErrorActionPreference = "Stop"

function Get-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-LatestFundingCollectPath {
    param([string]$ProjectRoot)
    $fundingDir = Join-Path $ProjectRoot "exports\trading-mvp\funding"
    $latest = Get-ChildItem -Path $fundingDir -Filter "funding_collect_*.jsonl" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "No funding_collect_*.jsonl files found in $fundingDir"
    }
    return $latest.FullName
}

function Get-JsonObject {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Get-JsonlLineCount {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return 0
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $stream = [System.IO.File]::Open($resolved, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $reader = [System.IO.StreamReader]::new($stream)
        try {
            $count = 0
            while ($null -ne $reader.ReadLine()) {
                $count++
            }
            return $count
        } finally {
            $reader.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Get-CycleIntervalSec {
    param($Manifest)
    $defaultInterval = 300.0
    if (-not $Manifest -or -not $Manifest.cycle_summaries -or $Manifest.cycle_summaries.Count -lt 2) {
        return $defaultInterval
    }
    $summaries = @($Manifest.cycle_summaries)
    $intervals = @()
    $start = [Math]::Max(1, $summaries.Count - 10)
    for ($i = $start; $i -lt $summaries.Count; $i++) {
        $prev = $summaries[$i - 1]
        $cur = $summaries[$i]
        if ($null -ne $prev.ts -and $null -ne $cur.ts) {
            $delta = [double]$cur.ts - [double]$prev.ts
            if ($delta -gt 0) {
                $intervals += $delta
            }
        }
    }
    if ($intervals.Count -eq 0) {
        return $defaultInterval
    }
    return ($intervals | Measure-Object -Average).Average
}

function Format-Duration {
    param([double]$Seconds)
    if ($null -eq $Seconds -or [double]::IsNaN($Seconds) -or $Seconds -lt 0) {
        return "n/a"
    }
    $span = [TimeSpan]::FromSeconds($Seconds)
    if ($span.TotalDays -ge 1) {
        return ("{0}d {1:00}h {2:00}m" -f [Math]::Floor($span.TotalDays), $span.Hours, $span.Minutes)
    }
    return ("{0:00}h {1:00}m {2:00}s" -f [Math]::Floor($span.TotalHours), $span.Minutes, $span.Seconds)
}

function Format-ProgressBar {
    param(
        [double]$ProgressPct,
        [int]$Width
    )
    $safePct = [Math]::Max(0.0, [Math]::Min(100.0, $ProgressPct))
    $filled = [int][Math]::Round(($safePct / 100.0) * $Width)
    $filled = [Math]::Min($filled, $Width)
    return "[" + ("#" * $filled) + ("-" * ($Width - $filled)) + "]"
}

function Get-ProcessSummary {
    param([string]$RawProcessIds)
    $ids = @(
        $RawProcessIds -split "," |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ } |
            ForEach-Object { [int]$_ }
    )
    if ($ids.Count -eq 0) {
        return [pscustomobject]@{
            configured = @()
            alive = @()
            missing = @()
            alive_count = 0
            configured_count = 0
        }
    }
    $alive = @()
    foreach ($id in $ids) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            $alive += [pscustomobject]@{
                id = $proc.Id
                name = $proc.ProcessName
                cpu = $proc.CPU
                start_time = $proc.StartTime
            }
        }
    }
    $aliveIds = @($alive | ForEach-Object { $_.id })
    $missing = @($ids | Where-Object { $aliveIds -notcontains $_ })
    return [pscustomobject]@{
        configured = $ids
        alive = $alive
        missing = $missing
        alive_count = $alive.Count
        configured_count = $ids.Count
    }
}

function Get-FundingWatchStatus {
    param(
        [string]$InputFile,
        [string]$ManifestFile,
        [string]$RawProcessIds,
        [double]$StaleAfter
    )
    $now = Get-Date
    $manifest = Get-JsonObject -Path $ManifestFile
    $lineCount = Get-JsonlLineCount -Path $InputFile
    $inputItem = Get-Item -LiteralPath $InputFile -ErrorAction SilentlyContinue
    $lastWrite = if ($inputItem) { $inputItem.LastWriteTime } else { $null }
    $lastWriteAgeSec = if ($lastWrite) { [Math]::Max(0.0, ($now - $lastWrite).TotalSeconds) } else { $null }
    $totalCycles = if ($manifest -and $null -ne $manifest.cycles) { [int]$manifest.cycles } else { 0 }
    $completedCycles = if ($manifest -and $null -ne $manifest.completed_cycles) { [int]$manifest.completed_cycles } else { 0 }
    $remainingCycles = [Math]::Max(0, $totalCycles - $completedCycles)
    $progressPct = if ($totalCycles -gt 0) { ($completedCycles / $totalCycles) * 100.0 } else { 0.0 }
    $intervalSec = Get-CycleIntervalSec -Manifest $manifest
    $etaSec = $remainingCycles * $intervalSec
    $etaLocal = $now.AddSeconds($etaSec)
    $manifestRows = if ($manifest -and $null -ne $manifest.rows) { [int]$manifest.rows } else { $null }
    $errors = if ($manifest -and $null -ne $manifest.errors) { [int]$manifest.errors } else { 0 }
    $attempts = $lineCount + $errors
    $errorRate = if ($attempts -gt 0) { $errors / $attempts } else { 0.0 }
    $final = $false
    if ($manifest -and $null -ne $manifest.final) {
        $final = [bool]$manifest.final
    }
    $lineMatch = $null -ne $manifestRows -and $lineCount -eq $manifestRows
    $stale = (-not $final) -and $null -ne $lastWriteAgeSec -and $lastWriteAgeSec -gt $StaleAfter
    $ready = $final -and $lineMatch
    $processSummary = Get-ProcessSummary -RawProcessIds $RawProcessIds
    $processMissing = $processSummary.configured_count -gt 0 -and $processSummary.alive_count -eq 0
    $state = if ($ready) {
        "ready_for_postprocess"
    } elseif ($stale) {
        "stale"
    } elseif ($processMissing) {
        "process_missing"
    } elseif ($final -and -not $lineMatch) {
        "line_count_mismatch"
    } else {
        "running_or_waiting"
    }
    return [pscustomobject]@{
        mode = "funding_watch"
        ts = $now.ToString("o")
        state = $state
        ready_for_postprocess = $ready
        input = $InputFile
        manifest = $ManifestFile
        final = $final
        completed_cycles = $completedCycles
        cycles = $totalCycles
        remaining_cycles = $remainingCycles
        progress_pct = $progressPct
        cycle_interval_sec = $intervalSec
        eta_sec = $etaSec
        eta_local = $etaLocal.ToString("yyyy-MM-dd HH:mm:ss zzz")
        line_count = $lineCount
        manifest_rows = $manifestRows
        line_count_matches_manifest = $lineMatch
        errors = $errors
        attempts = $attempts
        error_rate = $errorRate
        last_write = if ($lastWrite) { $lastWrite.ToString("yyyy-MM-dd HH:mm:ss zzz") } else { $null }
        last_write_age_sec = $lastWriteAgeSec
        stale_after_sec = $StaleAfter
        stale = $stale
        processes = $processSummary
    }
}

function Show-FundingWatchStatus {
    param(
        $Status,
        [int]$Width
    )
    $bar = Format-ProgressBar -ProgressPct $Status.progress_pct -Width $Width
    $aliveText = if ($Status.processes.configured_count -gt 0) {
        "alive $($Status.processes.alive_count)/$($Status.processes.configured_count)"
    } else {
        "not configured"
    }
    Write-Host "trading_mvp funding collect monitor"
    Write-Host ("Time:        {0}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Write-Host ("State:       {0}" -f $Status.state)
    Write-Host ("Progress:    {0} {1,6:N2}%  cycles {2}/{3}, remaining {4}" -f $bar, $Status.progress_pct, $Status.completed_cycles, $Status.cycles, $Status.remaining_cycles)
    Write-Host ("ETA:         {0}  local {1}  avg cycle {2:N1}s" -f (Format-Duration $Status.eta_sec), $Status.eta_local, $Status.cycle_interval_sec)
    Write-Host ("Rows:        {0} jsonl / {1} manifest  match={2}" -f $Status.line_count, $Status.manifest_rows, $Status.line_count_matches_manifest)
    Write-Host ("Errors:      {0} / attempts {1}  rate={2:P2}" -f $Status.errors, $Status.attempts, $Status.error_rate)
    Write-Host ("Last write:  {0}  age={1}  stale_after={2}s" -f $Status.last_write, (Format-Duration $Status.last_write_age_sec), $Status.stale_after_sec)
    Write-Host ("Processes:   {0}" -f $aliveText)
    if ($Status.processes.missing.Count -gt 0) {
        Write-Host ("Missing PID: {0}" -f (($Status.processes.missing | ForEach-Object { $_ }) -join ","))
    }
    Write-Host ("Input:       {0}" -f $Status.input)
    Write-Host ("Manifest:    {0}" -f $Status.manifest)
    Write-Host ""
    Write-Host "Controls: Ctrl+C to stop watcher. This does not stop the collector."
}

$projectRoot = Get-ProjectRoot
if (-not $InputPath) {
    $InputPath = Get-LatestFundingCollectPath -ProjectRoot $projectRoot
}
$InputPath = (Resolve-Path -LiteralPath $InputPath).Path
if (-not $ManifestPath) {
    $ManifestPath = [System.IO.Path]::ChangeExtension($InputPath, ".manifest.json")
}
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Manifest not found: $ManifestPath"
}
$ManifestPath = (Resolve-Path -LiteralPath $ManifestPath).Path
if (-not $SnapshotPath) {
    $SnapshotPath = Join-Path $projectRoot "exports\trading-mvp\run\funding_watch_latest.json"
}
$snapshotFile = [System.IO.FileInfo]$SnapshotPath
if ($snapshotFile.Directory -and -not $snapshotFile.Directory.Exists) {
    $snapshotFile.Directory.Create()
}

$resumeAttempted = $false
while ($true) {
    $status = Get-FundingWatchStatus -InputFile $InputPath -ManifestFile $ManifestPath -RawProcessIds $ProcessIds -StaleAfter $StaleAfterSec
    $status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $SnapshotPath -Encoding UTF8
    if (-not $NoClear) {
        Clear-Host
    }
    Show-FundingWatchStatus -Status $status -Width $ProgressWidth

    $shouldResume = $AutoResume -and -not $resumeAttempted -and (
        $status.state -eq "stale" -or $status.state -eq "process_missing"
    )
    if ($shouldResume) {
        if ([string]::IsNullOrWhiteSpace($ResumeCommand)) {
            Write-Host "AutoResume requested, but ResumeCommand is empty. No process started."
        } else {
            Write-Host "AutoResume starting hidden resume command..."
            Start-Process -FilePath "pwsh" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $ResumeCommand) -WindowStyle Hidden | Out-Null
            $resumeAttempted = $true
        }
    }

    if ($WatchOnce -or $status.ready_for_postprocess) {
        break
    }
    Start-Sleep -Seconds ([Math]::Max(1, $RefreshSec))
}
