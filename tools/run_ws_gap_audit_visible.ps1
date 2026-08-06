param(
    [string]$InputPath = "",
    [string]$PostprocessPath = "",
    [string]$OutputPath = "",
    [string]$RunLabel = "",
    [double]$GapThresholdSec = 300.0,
    [double]$BinSec = 300.0,
    [int]$TopN = 50,
    [int]$MinBboMarkets = 5,
    [int]$MinDepthMarkets = 5,
    [int]$MinTradeMarkets = 5,
    [int]$ProgressEveryLines = 1000000,
    [switch]$PlanOnly,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

try {
    Add-Type -Namespace ConsoleMode -Name Native -MemberDefinition @"
[DllImport("kernel32.dll", SetLastError=true)]
public static extern System.IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError=true)]
public static extern bool GetConsoleMode(System.IntPtr hConsoleHandle, out int lpMode);
[DllImport("kernel32.dll", SetLastError=true)]
public static extern bool SetConsoleMode(System.IntPtr hConsoleHandle, int dwMode);
"@ | Out-Null
    $stdInput = [ConsoleMode.Native]::GetStdHandle(-10)
    $mode = 0
    if ([ConsoleMode.Native]::GetConsoleMode($stdInput, [ref]$mode)) {
        $enableExtendedFlags = 0x0080
        $enableQuickEditMode = 0x0040
        $newMode = ($mode -bor $enableExtendedFlags) -band (-bnot $enableQuickEditMode)
        [ConsoleMode.Native]::SetConsoleMode($stdInput, $newMode) | Out-Null
    }
} catch {
    Write-Host ("QuickEdit guard unavailable: {0}" -f $_.Exception.Message)
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$script = Join-Path $repoRoot "trading_mvp\src\ws_gap_audit.py"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"

New-Item -ItemType Directory -Force -Path $backtestDir, $runDir | Out-Null
Set-Location $repoRoot

if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE") {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume or reject the incomplete run before WS gap audit."
    }
}

if ($PostprocessPath) {
    $PostprocessPath = (Resolve-Path -LiteralPath $PostprocessPath).Path
    $postprocess = Get-Content -Raw -LiteralPath $PostprocessPath | ConvertFrom-Json
    if (-not $InputPath -and $postprocess.normalized_output) {
        $InputPath = [string]$postprocess.normalized_output
    }
}

if (-not $InputPath) {
    throw "InputPath or PostprocessPath is required."
}

$InputPath = (Resolve-Path -LiteralPath $InputPath).Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$inputStem = [System.IO.Path]::GetFileNameWithoutExtension($InputPath)
$label = if ($RunLabel) { $RunLabel } else { "${inputStem}_gap_audit_$stamp" }
if (-not $OutputPath) {
    $OutputPath = Join-Path $backtestDir ("ws_gap_audit_{0}.json" -f $label)
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$consoleLog = Join-Path $runDir ("ws_gap_audit_{0}.console.log" -f $label)
$progressLog = Join-Path $runDir ("ws_gap_audit_{0}.progress.jsonl" -f $label)
$stdoutLog = Join-Path $runDir ("ws_gap_audit_{0}.stdout.log" -f $label)
$stderrLog = Join-Path $runDir ("ws_gap_audit_{0}.stderr.log" -f $label)

$pythonCandidates = @(
    $env:TRADING_MVP_PYTHON,
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
    "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe"
) | Where-Object { $_ }

$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = $pythonCmd.Source
    }
}
if (-not $python) {
    throw "Python not found. Set TRADING_MVP_PYTHON."
}

$plan = [ordered]@{
    mode = "ws_gap_audit_visible_plan"
    ok = $true
    would_run = (-not [bool]$PlanOnly)
    input = $InputPath
    postprocess = $PostprocessPath
    output = $OutputPath
    console_log = $consoleLog
    progress_log = $progressLog
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    config = [ordered]@{
        gap_threshold_sec = $GapThresholdSec
        bin_sec = $BinSec
        top_n = $TopN
        min_bbo_markets = $MinBboMarkets
        min_depth_markets = $MinDepthMarkets
        min_trade_markets = $MinTradeMarkets
        progress_every_lines = $ProgressEveryLines
    }
    blocked_actions = @("replay_grid_without_gap_audit_decision", "live_orders", "api_keys", "leverage_or_margin")
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Starting visible WS gap audit"
Write-Host "Input: $InputPath"
Write-Host "Output: $OutputPath"
Write-Host "Console log: $consoleLog"
Write-Host "Progress is printed every $ProgressEveryLines rows."

$argsList = @(
    $script,
    "--input", $InputPath,
    "--output", $OutputPath,
    "--gap-threshold-sec", ([string]$GapThresholdSec),
    "--bin-sec", ([string]$BinSec),
    "--top-n", ([string]$TopN),
    "--min-bbo-markets", ([string]$MinBboMarkets),
    "--min-depth-markets", ([string]$MinDepthMarkets),
    "--min-trade-markets", ([string]$MinTradeMarkets),
    "--progress-every-lines", ([string]$ProgressEveryLines),
    "--progress-file", $progressLog,
    "--no-progress"
)

$transcriptStarted = $false
try {
    Start-Transcript -Path $consoleLog -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

try {
    $child = Start-Process `
        -FilePath $python `
        -ArgumentList $argsList `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    Write-Host ("Worker PID: {0}" -f $child.Id)
    while (-not $child.HasExited) {
        Start-Sleep -Seconds 15
        $child.Refresh()
        $latestProgress = $null
        if (Test-Path -LiteralPath $progressLog) {
            $latestProgress = Get-Content -LiteralPath $progressLog -Tail 1 -ErrorAction SilentlyContinue
        }
        if ($latestProgress) {
            try {
                $p = $latestProgress | ConvertFrom-Json
                Write-Host ("[{0}] rows={1:n0} pct={2:n2}% speed={3:n0}/s elapsed={4:n1}s" -f (Get-Date -Format "HH:mm:ss"), [double]$p.rows, [double]$p.pct, [double]$p.rows_per_sec, [double]$p.elapsed_sec)
            } catch {
                Write-Host ("[{0}] progress: {1}" -f (Get-Date -Format "HH:mm:ss"), $latestProgress)
            }
        } else {
            Write-Host ("[{0}] waiting for first progress record; worker alive={1}" -f (Get-Date -Format "HH:mm:ss"), (-not $child.HasExited))
        }
    }
    if ($child.ExitCode -ne 0) {
        $stderrTail = if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 20 } else { @() }
        throw "ws-gap-audit failed with exit code $($child.ExitCode). stderr tail: $($stderrTail -join ' | ')"
    }
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $OutputPath)) {
    throw "Expected gap audit artifact was not created: $OutputPath"
}

$result = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
Write-Host ("Top-level diagnosis: {0}" -f $result.summary.top_level_diagnosis)
Write-Host ("Market gaps over threshold: {0}" -f $result.summary.market_gap_over_threshold)
Write-Host ("Market-kind gaps over threshold: {0}" -f $result.summary.market_kind_gap_over_threshold)
Write-Host ("Clean windows: {0}" -f $result.summary.clean_window_count)

if (-not $NoPause) {
    Read-Host "Press Enter to close this gap-audit window"
}
