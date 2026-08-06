param(
    [int]$Days = 7,
    [int]$PollIntervalSec = 300,
    [string]$Exchanges = "mexc,gateio",
    [int]$MaxSymbols = 300,
    [int]$MaxPairsPerExchange = 15,
    [double]$NotionalQuote = 100.0,
    [double]$FundingMaxSpotSpreadBps = 30.0,
    [double]$FundingMaxPerpSpreadBps = 30.0,
    [double]$FundingMaxAbsBasisBps = 500.0,
    [double]$FundingMinRate = -1.0,
    [double]$FundingMinVolume24hQuote = 0.0,
    [double]$FundingMinSpotTopNotionalQuote = 0.0,
    [double]$FundingSpotFeeBps = 10.0,
    [double]$FundingPerpFeeBps = 7.5,
    [double]$SlippageBps = 1.0,
    [double]$FundingTargetHoldIntervals = 3.0,
    [string]$RunLabel = "",
    [string]$WatchlistJson = "",
    [switch]$Resume,
    [switch]$NoPause,
    [switch]$ConfirmedLongRun,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"
$fundingDir = Join-Path $repoRoot "exports\trading-mvp\funding"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$runner = Join-Path $repoRoot "trading_mvp\run_mvp.ps1"
$watchlistScript = Join-Path $repoRoot "tools\funding_candidate_watchlist.ps1"
if (-not $WatchlistJson) {
    $WatchlistJson = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json"
}

if (-not $ConfirmedLongRun -and -not $PlanOnly) {
    throw "Explicit long-run confirmation is required. Re-run with -ConfirmedLongRun only after the user explicitly approves this visible funding collect, or use -PlanOnly to preview without starting."
}

New-Item -ItemType Directory -Force -Path $runDir, $fundingDir, (Split-Path $gatePath) | Out-Null
Set-Location $repoRoot

if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE" -and -not $Resume) {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume that run explicitly or clear/replace the gate before starting a new collect."
    }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$daysLabel = if ($Days -eq 1) { "1d" } else { "${Days}d" }
$label = if ($RunLabel) { $RunLabel } else { "funding_collect_${daysLabel}_spotliq_visible_$stamp" }
$cycles = [int][Math]::Ceiling(($Days * 24.0 * 3600.0) / [Math]::Max(1, $PollIntervalSec))
$output = Join-Path $fundingDir ("{0}.jsonl" -f $label)
$manifest = $output -replace "\.jsonl$", ".manifest.json"
$stdout = Join-Path $runDir ("{0}.out.log" -f $label)
$stderr = Join-Path $runDir ("{0}.err.log" -f $label)

$watchlist = $null
if (-not (Test-Path -LiteralPath $WatchlistJson)) {
    if (Test-Path -LiteralPath $watchlistScript) {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $watchlistScript -Json | Out-Null
    }
}
if (Test-Path -LiteralPath $WatchlistJson) {
    $watchlist = Get-Content -Raw -LiteralPath $WatchlistJson | ConvertFrom-Json
} else {
    throw "Funding candidate watchlist not found: $WatchlistJson. Run tools\funding_candidate_watchlist.ps1 before launching a long collect."
}
$watchlistRecommended = @($watchlist.recommended | Select-Object -First 15)
$watchlistRecommendedCompact = @(
    $watchlistRecommended | ForEach-Object {
        [pscustomobject][ordered]@{
            priority = $_.priority
            exchange = $_.exchange
            base = $_.base
            spot_symbol = $_.spot_symbol
            perp_symbol = $_.perp_symbol
            funding_avg_bps = $_.funding_avg_bps
            risk_adjusted_edge_bps = $_.risk_adjusted_edge_bps
            watch_score = $_.watch_score
        }
    }
)

$argsList = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner,
    "-Action", "funding-collect",
    "-Exchanges", $Exchanges,
    "-MaxSymbols", $MaxSymbols,
    "-MaxPairsPerExchange", $MaxPairsPerExchange,
    "-Cycles", $cycles,
    "-PollIntervalSec", $PollIntervalSec,
    "-NotionalQuote", $NotionalQuote,
    "-FundingMaxSpotSpreadBps", $FundingMaxSpotSpreadBps,
    "-FundingMaxPerpSpreadBps", $FundingMaxPerpSpreadBps,
    "-FundingMaxAbsBasisBps", $FundingMaxAbsBasisBps,
    "-FundingMinRate", $FundingMinRate,
    "-FundingMinVolume24hQuote", $FundingMinVolume24hQuote,
    "-FundingMinSpotTopNotionalQuote", $FundingMinSpotTopNotionalQuote,
    "-FundingSpotFeeBps", $FundingSpotFeeBps,
    "-FundingPerpFeeBps", $FundingPerpFeeBps,
    "-SlippageBps", $SlippageBps,
    "-FundingTargetHoldIntervals", $FundingTargetHoldIntervals,
    "-FundingMinExpectedNetCarryBps", -1000000000,
    "-OutputPath", $output
)
if ($Resume) {
    $argsList += "-FundingResume"
}

if ($PlanOnly) {
    $plan = [ordered]@{
        mode = "funding_collect_visible_plan"
        would_start = $false
        requires_confirmed_long_run = $true
        confirmed_long_run = [bool]$ConfirmedLongRun
        days = $Days
        poll_interval_sec = $PollIntervalSec
        cycles = $cycles
        exchanges = $Exchanges
        max_symbols = $MaxSymbols
        max_pairs_per_exchange = $MaxPairsPerExchange
        notional_quote = $NotionalQuote
        output_path = $output
        manifest_path = $manifest
        stdout_path = $stdout
        stderr_path = $stderr
        gate_path = $gatePath
        runner = $runner
        watchlist_path = $WatchlistJson
        watchlist_decision = $watchlist.decision
        watchlist_warning = $watchlist.warning
        watchlist_summary = $watchlist.summary
        watchlist_recommended = $watchlistRecommendedCompact
        acceptance_warning = "Watchlist is predeclared research focus only. It cannot accept a strategy; final-review/OOS/walk-forward/stress under current costs remain required."
        command_after_explicit_approval = "pwsh -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Days $Days -ConfirmedLongRun"
    }
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

$gate = [ordered]@{
    schema = "active_run_gate_v1"
    project = "trading_mvp"
    run_id = $label
    status = "RUNNING"
    created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    purpose = "Visible research-only funding/basis collect; blocks next goal step until final manifest."
    blocking_rule = "While status is RUNNING, do not run goal postprocess, grid/search, analysis expansion, code changes, or new collectors. Only status/ETA checks are allowed."
    monitor_pid = $PID
    process_ids = @($PID)
    monitor_script = $PSCommandPath
    output_path = $output
    manifest_path = $manifest
    total_cycles = $cycles
    poll_interval_sec = $PollIntervalSec
    ready_condition = "manifest.final == true AND manifest.completed_cycles >= manifest.cycles"
    watchlist_path = $WatchlistJson
    watchlist_decision = $watchlist.decision
    watchlist_warning = $watchlist.warning
    watchlist_summary = $watchlist.summary
    watchlist_recommended = $watchlistRecommendedCompact
    status_check_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"
    next_step_after_ready = "Run guarded funding-final-review on the completed JSONL and compare results against the predeclared watchlist; then update project viability analysis. Do not treat as investment advice."
}
$gate | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $gatePath

Write-Host "Starting visible funding collect"
Write-Host "Run id: $label"
Write-Host "Cycles: $cycles, poll interval sec: $PollIntervalSec, expected days: $Days"
Write-Host "Output: $output"
Write-Host "Manifest: $manifest"
Write-Host "Stdout: $stdout"
Write-Host "Stderr: $stderr"
Write-Host "Watchlist: $WatchlistJson"
Write-Host ("Watchlist summary: primary={0}, secondary={1}, diagnostic={2}, rank_eligible={3}" -f $watchlist.summary.primary_7d_watch, $watchlist.summary.secondary_7d_watch, $watchlist.summary.diagnostic_coverage, $watchlist.summary.rank_eligible)
Write-Host "Top watchlist markets:"
foreach ($row in @($watchlistRecommendedCompact | Select-Object -First 10)) {
    Write-Host ("  - {0}:{1} {2} score={3} avg_funding={4}bps risk_edge={5}bps" -f $row.exchange, $row.base, $row.priority, $row.watch_score, $row.funding_avg_bps, $row.risk_adjusted_edge_bps)
}
Write-Host "Watchlist is research focus only, not a trade signal or acceptance."
Write-Host "Status check: pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker"

$pwshPath = (Get-Command pwsh -ErrorAction Stop).Source
$proc = Start-Process -FilePath $pwshPath -ArgumentList $argsList -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$gate.process_ids = @($PID, $proc.Id)
$gate | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $gatePath

Write-Host "Collector PID: $($proc.Id)"

while (-not $proc.HasExited) {
    try {
        $lineCount = if (Test-Path -LiteralPath $output) { (Get-Content -LiteralPath $output | Measure-Object -Line).Lines } else { 0 }
        if (Test-Path -LiteralPath $manifest) {
            $m = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
            $completed = [int]($m.completed_cycles ?? 0)
            $total = [int]($m.cycles ?? $cycles)
            $pct = if ($total -gt 0) { [Math]::Round(($completed / $total) * 100.0, 2) } else { 0 }
            $lastWrite = if (Test-Path -LiteralPath $output) { (Get-Item -LiteralPath $output).LastWriteTime } else { $null }
            $age = if ($lastWrite) { [Math]::Round(((Get-Date) - $lastWrite).TotalSeconds, 1) } else { $null }
            Write-Host ("[{0}] PID={1} cycles={2}/{3} progress={4}% rows={5} lines={6} errors={7} final={8} last_write_age_sec={9}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id, $completed, $total, $pct, $m.rows, $lineCount, $m.errors, $m.final, $age)
        } else {
            Write-Host ("[{0}] PID={1} manifest not created yet lines={2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id, $lineCount)
        }
        if ((Test-Path -LiteralPath $stderr) -and (Get-Item -LiteralPath $stderr).Length -gt 0) {
            Write-Host "--- stderr tail ---"
            Get-Content -LiteralPath $stderr -Tail 5
            Write-Host "--- end stderr tail ---"
        }
    } catch {
        Write-Host ("[{0}] monitor error: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message)
    }
    Start-Sleep -Seconds 60
    try { $proc.Refresh() } catch {}
}

$proc.Refresh()
Write-Host "Collector exited. ExitCode=$($proc.ExitCode)"
$finalStatus = "STOPPED_INCOMPLETE"
try {
    $m = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
    $lineCount = if (Test-Path -LiteralPath $output) { (Get-Content -LiteralPath $output | Measure-Object -Line).Lines } else { 0 }
    Write-Host ("Final status: final={0} cycles={1}/{2} rows={3} lines={4} errors={5}" -f $m.final, $m.completed_cycles, $m.cycles, $m.rows, $lineCount, $m.errors)
    if (($m.final -eq $true) -and ([int]$m.completed_cycles -ge [int]$m.cycles)) {
        $finalStatus = "READY_FOR_POSTPROCESS"
    }
} catch {
    Write-Host ("Final manifest read failed: {0}" -f $_.Exception.Message)
}

$gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$gate.status = $finalStatus
$gate.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
$gate.process_ids = @()
$gate | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $gatePath

if ((Test-Path -LiteralPath $stdout) -and (Get-Item -LiteralPath $stdout).Length -gt 0) {
    Write-Host "--- stdout tail ---"
    Get-Content -LiteralPath $stdout -Tail 20
}
if ((Test-Path -LiteralPath $stderr) -and (Get-Item -LiteralPath $stderr).Length -gt 0) {
    Write-Host "--- stderr tail ---"
    Get-Content -LiteralPath $stderr -Tail 20
}

if (-not $NoPause) {
    Read-Host "Press Enter to close this monitor"
}
