param(
    [string]$UniversePath = "coins_not_on_binance_full_2026-05-29.csv",
    [string]$OutputRoot = "",
    [int]$HistoryDays = 56,
    [int]$TargetBases = 50,
    [string]$Exchanges = "mexc,gateio,bitget",
    [string]$Timeframes = "15m,1h,4h",
    [int]$CandlesPerRequest = 1000,
    [double]$SleepSec = 0.25,
    [int]$TimeoutSec = 15,
    [int]$MaxRetries = 2,
    [int]$ProgressEvery = 10,
    [string]$RunId = "",
    [int]$MaxJobs = 0,
    [switch]$ConfirmedSlowLiquidityHistoryCollect,
    [switch]$ResumeIncomplete,
    [switch]$PlanOnly,
    [switch]$NoPause,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$collectorModule = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_history_collector.py"
$requiredApprovalText = "подтверждаю visible slow-liquidity OHLCV history collect"

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return (Join-Path $repoRoot $PathValue)
}

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-Gate {
    param([Parameter(Mandatory = $true)]$Gate)
    New-Item -ItemType Directory -Force -Path (Split-Path $gatePath) | Out-Null
    $Gate | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $gatePath -Encoding UTF8
}

function ConvertTo-PSLiteral {
    param([AllowEmptyString()][string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Split-List {
    param([string]$Value)
    return @($Value -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Resolve-Python {
    $pythonCandidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    ) | Where-Object { $_ }
    $python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $python) {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) {
            $python = $pythonCmd.Source
        }
    }
    if (-not $python) {
        throw "Python runtime not found."
    }
    return $python
}

if (-not $PlanOnly -and -not $ConfirmedSlowLiquidityHistoryCollect) {
    throw "Explicit approval is required. The user must say exactly: $requiredApprovalText, then run with -ConfirmedSlowLiquidityHistoryCollect. Use -PlanOnly to preview."
}

if (-not (Test-Path -LiteralPath $collectorModule)) {
    throw "Collector module not found: $collectorModule"
}

$universeResolved = Resolve-RepoPath $UniversePath
if (-not (Test-Path -LiteralPath $universeResolved)) {
    throw "Universe path not found: $universeResolved"
}

$exchangeList = Split-List $Exchanges
$timeframeList = Split-List $Timeframes
$unknownTimeframes = @($timeframeList | Where-Object { $_ -notin @("1m", "5m", "15m", "1h", "4h") })
if ($unknownTimeframes.Count -gt 0) {
    throw "Unsupported timeframes: $($unknownTimeframes -join ', ')"
}

if (-not $OutputRoot) {
    if (Test-Path -LiteralPath "E:\") {
        $OutputRoot = "E:\trading_mvp\slow-liquidity-history"
    } else {
        $OutputRoot = Join-Path $repoRoot "exports\trading-mvp\slow-liquidity-history"
    }
}
$outputRootResolved = Resolve-RepoPath $OutputRoot

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
$rawGate = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { $null }
$gateDecision = if ($rawGate -and $rawGate.PSObject.Properties.Name -contains "next_goal_decision") { [string]$rawGate.next_goal_decision } else { [string]$gate.next_goal_decision }
$gateStatus = [string]$gate.status

$resumeFromGate = $false
if ($ResumeIncomplete) {
    if ($gateStatus -ne "STOPPED_INCOMPLETE" -or $gateDecision -ne "SLOW_LIQUIDITY_HISTORY_COLLECT_STOPPED_INCOMPLETE") {
        throw "ResumeIncomplete was requested, but gate is not SLOW_LIQUIDITY_HISTORY_COLLECT_STOPPED_INCOMPLETE."
    }
    $resumeFromGate = $true
    if (-not $RunId) {
        $RunId = [string]$gate.run_id
    }
    if ($rawGate -and $rawGate.PSObject.Properties.Name -contains "output_root" -and [string]$rawGate.output_root) {
        $outputRootResolved = [string]$rawGate.output_root
    }
}

if (-not $RunId) {
    $RunId = "slow_liquidity_history_collect_$((Get-Date).ToString('yyyyMMdd_HHmmss'))"
}

$runDir = Join-Path $outputRootResolved $RunId
$outputJsonl = Join-Path $runDir "ohlcv.jsonl"
$manifestPath = Join-Path $runDir "manifest.json"
$stdoutPath = Join-Path $runDir "stdout.log"
$stderrPath = Join-Path $runDir "stderr.log"
$monitorErrorPath = Join-Path $runDir "monitor_error.log"
$monitorScriptPath = Join-Path $runDir "run_visible_monitor.ps1"
$python = Resolve-Python

$estimatedRequestsPerMarket = 0
foreach ($tf in $timeframeList) {
    $interval = switch ($tf) {
        "1m" { 60 }
        "5m" { 300 }
        "15m" { 900 }
        "1h" { 3600 }
        "4h" { 14400 }
        default { 3600 }
    }
    $candles = [Math]::Ceiling(($HistoryDays * 86400.0) / $interval) + 1
    $estimatedRequestsPerMarket += [Math]::Ceiling($candles / [Math]::Max(1, $CandlesPerRequest))
}
$estimatedJobs = $TargetBases * $exchangeList.Count * $timeframeList.Count
$estimatedRequests = $TargetBases * $exchangeList.Count * $estimatedRequestsPerMarket
$estimatedRuntimeMin = [Math]::Round((($estimatedRequests * [Math]::Max(0.0, $SleepSec)) + ($estimatedRequests * 0.6)) / 60.0, 1)

$plan = [ordered]@{
    mode = "slow_liquidity_history_collect_visible_plan"
    would_start = $false
    confirmed_slow_liquidity_history_collect = [bool]$ConfirmedSlowLiquidityHistoryCollect
    resume_incomplete = [bool]$ResumeIncomplete
    research_only = $true
    public_data_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    required_approval_text = $requiredApprovalText
    gate_status = $gateStatus
    gate_next_goal_decision = $gateDecision
    run_id = $RunId
    run_dir = $runDir
    output_root = $outputRootResolved
    universe_path = $universeResolved
    history_days = $HistoryDays
    target_bases = $TargetBases
    exchanges = $exchangeList
    timeframes = $timeframeList
    estimated_jobs = $estimatedJobs
    estimated_total_requests = $estimatedRequests
    estimated_runtime_min = $estimatedRuntimeMin
    output_jsonl = $outputJsonl
    manifest_path = $manifestPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    monitor_error_path = $monitorErrorPath
    monitor_script_path = $monitorScriptPath
    command_after_explicit_approval = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ConfirmedSlowLiquidityHistoryCollect"
    resume_command_if_stopped = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ConfirmedSlowLiquidityHistoryCollect -ResumeIncomplete -RunId $RunId"
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 10
    exit 0
}

if ($gateStatus -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ($gateStatus -eq "STOPPED_INCOMPLETE" -and -not $resumeFromGate) {
    throw "Active run gate is STOPPED_INCOMPLETE. Resume that run or explicitly resolve it before starting a new collect."
}
if (-not $resumeFromGate) {
    if ($gateStatus -ne "READY_FOR_POSTPROCESS") {
        throw "Unexpected gate status=$gateStatus. Expected READY_FOR_POSTPROCESS with slow-liquidity approval decision."
    }
    if ($gateDecision -ne "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL") {
        throw "Unexpected gate next_goal_decision=$gateDecision"
    }
    if ([bool]$gate.replay_allowed) {
        throw "Unexpected gate replay_allowed=true before slow-liquidity history collect."
    }
    if ($rawGate -and $rawGate.PSObject.Properties.Name -contains "requires_explicit_user_approval_for_actual_collect" -and -not [bool]$rawGate.requires_explicit_user_approval_for_actual_collect) {
        throw "Gate does not require explicit approval; refusing to start outside approval contract."
    }
}

New-Item -ItemType Directory -Force -Path $runDir, (Split-Path $gatePath) | Out-Null

if (-not $resumeFromGate) {
    foreach ($path in @($outputJsonl, $manifestPath, "$manifestPath.tmp", $stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) {
            $backup = "$path.previous.$((Get-Date).ToString('yyyyMMdd_HHmmss'))"
            Move-Item -LiteralPath $path -Destination $backup -Force
        }
    }
}

$resumeLiteral = if ($resumeFromGate) { '$true' } else { '$false' }
$noPauseLiteral = if ($NoPause) { '$true' } else { '$false' }
$maxJobsLiteral = [string]$MaxJobs

$monitorScript = @"
`$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(`$false)
`$OutputEncoding = [System.Text.UTF8Encoding]::new(`$false)

`$repoRoot = $(ConvertTo-PSLiteral $repoRoot)
`$gatePath = $(ConvertTo-PSLiteral $gatePath)
`$gateChecker = $(ConvertTo-PSLiteral $gateChecker)
`$launcherScript = $(ConvertTo-PSLiteral $PSCommandPath)
`$python = $(ConvertTo-PSLiteral $python)
`$collectorModule = $(ConvertTo-PSLiteral $collectorModule)
`$runId = $(ConvertTo-PSLiteral $RunId)
`$runDir = $(ConvertTo-PSLiteral $runDir)
`$outputRoot = $(ConvertTo-PSLiteral $outputRootResolved)
`$universePath = $(ConvertTo-PSLiteral $universeResolved)
`$outputJsonl = $(ConvertTo-PSLiteral $outputJsonl)
`$manifestPath = $(ConvertTo-PSLiteral $manifestPath)
`$stdoutPath = $(ConvertTo-PSLiteral $stdoutPath)
`$stderrPath = $(ConvertTo-PSLiteral $stderrPath)
`$monitorErrorPath = $(ConvertTo-PSLiteral $monitorErrorPath)
`$approvalText = $(ConvertTo-PSLiteral $requiredApprovalText)
`$exchanges = $(ConvertTo-PSLiteral ($exchangeList -join ","))
`$timeframes = $(ConvertTo-PSLiteral ($timeframeList -join ","))
`$historyDays = $HistoryDays
`$targetBases = $TargetBases
`$candlesPerRequest = $CandlesPerRequest
`$sleepSec = $SleepSec
`$timeoutSec = $TimeoutSec
`$maxRetries = $MaxRetries
`$progressEvery = $ProgressEvery
`$resume = $resumeLiteral
`$noPause = $noPauseLiteral
`$maxJobs = $maxJobsLiteral

trap {
    `$message = (`$_ | Out-String)
    try { `$message | Set-Content -LiteralPath `$monitorErrorPath -Encoding UTF8 } catch {}
    Write-Host "Monitor fatal error: `$(`$_.Exception.Message)" -ForegroundColor Red
    try {
        `$gateDoc = Get-Content -Raw -LiteralPath `$gatePath | ConvertFrom-Json
        Set-JsonProperty -Object `$gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
        Set-JsonProperty -Object `$gateDoc -Name "status" -Value "STOPPED_INCOMPLETE"
        Set-JsonProperty -Object `$gateDoc -Name "final" -Value `$false
        Set-JsonProperty -Object `$gateDoc -Name "stop_reason" -Value "monitor_error"
        Set-JsonProperty -Object `$gateDoc -Name "monitor_error_path" -Value `$monitorErrorPath
        Set-JsonProperty -Object `$gateDoc -Name "next_goal_decision" -Value "SLOW_LIQUIDITY_HISTORY_COLLECT_STOPPED_INCOMPLETE"
        Set-JsonProperty -Object `$gateDoc -Name "next_goal_reason" -Value "Visible slow-liquidity monitor failed before/while running collector; inspect monitor_error/stdout/stderr and resume visibly."
        Set-JsonProperty -Object `$gateDoc -Name "resume_command" -Value "pwsh -NoProfile -ExecutionPolicy Bypass -File ```"`$launcherScript```" -ConfirmedSlowLiquidityHistoryCollect -ResumeIncomplete -RunId `$runId -OutputRoot ```"`$outputRoot```""
        Write-Gate `$gateDoc
    } catch {
        Write-Host "Failed to update active gate after monitor error: `$(`$_.Exception.Message)" -ForegroundColor Yellow
    }
    if (-not `$noPause) {
        Read-Host "Press Enter to close this failed visible collector window"
    }
    exit 1
}

function Set-JsonProperty {
    param(`$Object, [string]`$Name, `$Value)
    if (`$Object.PSObject.Properties.Name -contains `$Name) {
        `$Object.`$Name = `$Value
    } else {
        `$Object | Add-Member -NotePropertyName `$Name -NotePropertyValue `$Value
    }
}

function Write-Gate {
    param(`$Gate)
    `$Gate | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath `$gatePath -Encoding UTF8
}

function ConvertTo-ProcessArgument {
    param([AllowEmptyString()][string]`$Value)
    if (`$Value -notmatch '[\s"]') { return `$Value }
    return '"' + (`$Value -replace '"', '\"') + '"'
}

Set-Location `$repoRoot

Write-Host "Starting visible slow-liquidity OHLCV history collect" -ForegroundColor Cyan
Write-Host "Run id: `$runId"
Write-Host "Universe: `$universePath"
Write-Host "Exchanges: `$exchanges"
Write-Host "Timeframes: `$timeframes"
Write-Host "History days: `$historyDays; target bases: `$targetBases"
Write-Host "Output: `$outputJsonl"
Write-Host "Manifest: `$manifestPath"
Write-Host "Stdout: `$stdoutPath"
Write-Host "Stderr: `$stderrPath"
Write-Host "Status check: pwsh -NoProfile -ExecutionPolicy Bypass -File ```"`$gateChecker```" -Json"

`$argsList = @(
    `$collectorModule,
    "--run-id", `$runId,
    "--universe", `$universePath,
    "--output-jsonl", `$outputJsonl,
    "--manifest", `$manifestPath,
    "--confirmed-approval-text", `$approvalText,
    "--exchanges", `$exchanges,
    "--granularities", `$timeframes,
    "--history-days", [string]`$historyDays,
    "--target-bases", [string]`$targetBases,
    "--candles-per-request", [string]`$candlesPerRequest,
    "--sleep-sec", [string]`$sleepSec,
    "--timeout-sec", [string]`$timeoutSec,
    "--max-retries", [string]`$maxRetries,
    "--progress-every", [string]`$progressEvery
)
if (`$resume) { `$argsList += "--resume" }
if (`$maxJobs -gt 0) { `$argsList += @("--max-jobs", [string]`$maxJobs) }

`$argumentLine = (`$argsList | ForEach-Object { ConvertTo-ProcessArgument -Value ([string]`$_) }) -join " "
`$proc = Start-Process -FilePath `$python -ArgumentList `$argumentLine -RedirectStandardOutput `$stdoutPath -RedirectStandardError `$stderrPath -PassThru
Write-Host "Collector PID: `$(`$proc.Id)"

`$gateDoc = Get-Content -Raw -LiteralPath `$gatePath | ConvertFrom-Json
Set-JsonProperty -Object `$gateDoc -Name "process_ids" -Value @(`$PID, `$proc.Id)
Set-JsonProperty -Object `$gateDoc -Name "collector_pid" -Value `$proc.Id
Set-JsonProperty -Object `$gateDoc -Name "monitor_pid" -Value `$PID
Set-JsonProperty -Object `$gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Write-Gate `$gateDoc

while (-not `$proc.HasExited) {
    try {
        `$fileSizeMb = if (Test-Path -LiteralPath `$outputJsonl) { [Math]::Round((Get-Item -LiteralPath `$outputJsonl).Length / 1MB, 2) } else { 0 }
        if (Test-Path -LiteralPath `$manifestPath) {
            `$manifest = Get-Content -Raw -LiteralPath `$manifestPath | ConvertFrom-Json
            `$completed = [int]`$manifest.completed_market_granularity_requests
            `$total = [int]`$manifest.planned_market_granularity_requests
            `$pct = if (`$total -gt 0) { [Math]::Round((`$completed / `$total) * 100.0, 2) } else { 0 }
            `$lastWrite = if (Test-Path -LiteralPath `$outputJsonl) { (Get-Item -LiteralPath `$outputJsonl).LastWriteTime } else { `$null }
            `$age = if (`$lastWrite) { [Math]::Round(((Get-Date) - `$lastWrite).TotalSeconds, 1) } else { `$null }
            Write-Host ("[{0}] PID={1} progress={2}/{3} ({4}%) rows={5} ohlcv={6} placeholders={7} errors={8} http={9} size_mb={10} final={11} last_write_age_sec={12}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), `$proc.Id, `$completed, `$total, `$pct, `$manifest.rows, `$manifest.ohlcv_rows, `$manifest.placeholder_rows, `$manifest.errors, `$manifest.http_requests, `$fileSizeMb, `$manifest.final, `$age)
        } else {
            Write-Host ("[{0}] PID={1} manifest not created yet size_mb={2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), `$proc.Id, `$fileSizeMb)
        }
        if ((Test-Path -LiteralPath `$stderrPath) -and (Get-Item -LiteralPath `$stderrPath).Length -gt 0) {
            Write-Host "--- stderr tail ---" -ForegroundColor Yellow
            Get-Content -LiteralPath `$stderrPath -Tail 5
            Write-Host "--- end stderr tail ---" -ForegroundColor Yellow
        }
    } catch {
        Write-Host ("[{0}] monitor error: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), `$_.Exception.Message) -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 15
}

`$proc.Refresh()
`$finalGate = Get-Content -Raw -LiteralPath `$gatePath | ConvertFrom-Json
`$finalManifest = `$null
if (Test-Path -LiteralPath `$manifestPath) {
    `$finalManifest = Get-Content -Raw -LiteralPath `$manifestPath | ConvertFrom-Json
}

`$completedOk = (`$proc.ExitCode -eq 0 -and `$finalManifest -and [bool]`$finalManifest.final)
Set-JsonProperty -Object `$finalGate -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty -Object `$finalGate -Name "status" -Value (`$(if (`$completedOk) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }))
Set-JsonProperty -Object `$finalGate -Name "final" -Value ([bool]`$completedOk)
Set-JsonProperty -Object `$finalGate -Name "stop_reason" -Value (`$(if (`$completedOk) { "completed" } else { "collector_exit_`$(`$proc.ExitCode)" }))
Set-JsonProperty -Object `$finalGate -Name "monitor_pid_alive" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "replay_allowed" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "grid_allowed" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "paper_forward_allowed" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "live_orders" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "api_keys" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "leverage_or_margin" -Value `$false
Set-JsonProperty -Object `$finalGate -Name "next_goal_decision" -Value (`$(if (`$completedOk) { "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY" } else { "SLOW_LIQUIDITY_HISTORY_COLLECT_STOPPED_INCOMPLETE" }))
Set-JsonProperty -Object `$finalGate -Name "next_goal_reason" -Value (`$(if (`$completedOk) { "Slow-liquidity OHLCV history collect completed: rows=`$(`$finalManifest.rows), ohlcv=`$(`$finalManifest.ohlcv_rows), placeholders=`$(`$finalManifest.placeholder_rows), errors=`$(`$finalManifest.errors)." } else { "Slow-liquidity OHLCV history collect did not complete; inspect stdout/stderr/manifest and resume visibly before data-quality/replay." }))
Set-JsonProperty -Object `$finalGate -Name "next_step_after_ready" -Value "Run guarded slow-liquidity history data-quality gate. Do not run replay/grid/live/API/paper-forward until data-quality and fixed-signal gates pass."
Set-JsonProperty -Object `$finalGate -Name "raw_gate_next_step_after_ready" -Value `$finalGate.next_step_after_ready
Set-JsonProperty -Object `$finalGate -Name "last_slow_liquidity_history_collect_manifest_path" -Value `$manifestPath
Set-JsonProperty -Object `$finalGate -Name "last_slow_liquidity_history_collect_output_path" -Value `$outputJsonl
Set-JsonProperty -Object `$finalGate -Name "last_slow_liquidity_history_collect_stdout_path" -Value `$stdoutPath
Set-JsonProperty -Object `$finalGate -Name "last_slow_liquidity_history_collect_stderr_path" -Value `$stderrPath
Set-JsonProperty -Object `$finalGate -Name "resume_command" -Value "pwsh -NoProfile -ExecutionPolicy Bypass -File ```"`$launcherScript```" -ConfirmedSlowLiquidityHistoryCollect -ResumeIncomplete -RunId `$runId -OutputRoot ```"`$outputRoot```""
if (`$finalManifest) {
    Set-JsonProperty -Object `$finalGate -Name "rows" -Value ([int]`$finalManifest.rows)
    Set-JsonProperty -Object `$finalGate -Name "errors" -Value ([int]`$finalManifest.errors)
    Set-JsonProperty -Object `$finalGate -Name "expected_outputs_complete" -Value ([bool]`$finalManifest.final)
}
Write-Gate `$finalGate

Write-Host ""
Write-Host "Slow-liquidity OHLCV history collect finished" -ForegroundColor Cyan
Write-Host "Exit code: `$(`$proc.ExitCode)"
Write-Host "Gate status: `$(`$finalGate.status)"
Write-Host "Decision: `$(`$finalGate.next_goal_decision)"
Write-Host "Manifest: `$manifestPath"
Write-Host "Output: `$outputJsonl"
if (`$finalManifest) {
    Write-Host "Rows: `$(`$finalManifest.rows), ohlcv: `$(`$finalManifest.ohlcv_rows), placeholders: `$(`$finalManifest.placeholder_rows), errors: `$(`$finalManifest.errors), http: `$(`$finalManifest.http_requests)"
}

if (-not `$noPause) {
    Write-Host ""
    Read-Host "Press Enter to close this visible collector window"
}
"@

Set-Content -LiteralPath $monitorScriptPath -Value $monitorScript -Encoding UTF8

$activeGate = [ordered]@{
    schema = "active_run_gate_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "RUNNING"
    created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    purpose = "Visible research-only public OHLCV slow-liquidity history collect; no replay/grid/live/API keys."
    blocking_rule = "While status is RUNNING, do not run replay/grid/backtest/paper-forward/new collectors/code edits. Only status/ETA checks are allowed."
    monitor_pid = $null
    process_ids = @()
    monitor_script = $monitorScriptPath
    output_root = $outputRootResolved
    output_path = $outputJsonl
    output_kind = "jsonl"
    manifest_path = $manifestPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    monitor_error_path = $monitorErrorPath
    universe_path = $universeResolved
    selected_bases = $TargetBases
    exchanges = $exchangeList
    timeframes = $timeframeList
    history_days = $HistoryDays
    estimated_jobs = $estimatedJobs
    estimated_total_requests = $estimatedRequests
    estimated_runtime_min = $estimatedRuntimeMin
    replay_allowed = $false
    grid_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    status_check_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
    ready_condition = "manifest.final == true AND decision == SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
    next_step_after_ready = "Run guarded slow-liquidity history data-quality gate; no replay/grid/live/API/paper-forward until data-quality and fixed-signal gates pass."
    resume_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ConfirmedSlowLiquidityHistoryCollect -ResumeIncomplete -RunId $RunId -OutputRoot `"$outputRootResolved`""
}
Write-Gate $activeGate

$visibleShell = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if ($visibleShell) {
    $visibleArgs = @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $monitorScriptPath)
} else {
    $visibleShell = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
    if (-not $visibleShell) {
        $visibleShell = "powershell.exe"
    }
    $visibleArgs = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $monitorScriptPath)
}
$monitorProc = Start-Process -FilePath $visibleShell -ArgumentList $visibleArgs -PassThru
$activeGate.monitor_pid = $monitorProc.Id
$activeGate.process_ids = @($monitorProc.Id)
$activeGate.visible_terminal_pid = $monitorProc.Id
$activeGate.updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
Write-Gate $activeGate

$result = $plan
$result.would_start = $true
$result.started = $true
$result.visible_terminal_pid = $monitorProc.Id
$result.status_check_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"

if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "Visible slow-liquidity OHLCV history collect started" -ForegroundColor Cyan
    Write-Host "Run id: $RunId"
    Write-Host "Visible terminal PID: $($monitorProc.Id)"
    Write-Host "Estimated requests: $estimatedRequests; estimated runtime min: $estimatedRuntimeMin"
    Write-Host "Output: $outputJsonl"
    Write-Host "Manifest: $manifestPath"
    Write-Host "Status: pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
}
