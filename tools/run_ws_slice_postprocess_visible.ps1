param(
    [string]$GapAuditPath = "",
    [string]$PostprocessPath = "",
    [string]$InputPath = "",
    [string]$SourceManifestPath = "",
    [double]$StartTs = 0.0,
    [double]$EndTs = 0.0,
    [int]$CleanWindowIndex = 0,
    [string]$RunLabel = "",
    [switch]$PlanOnly,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$script = Join-Path $repoRoot "trading_mvp\src\ws_slice_postprocess.py"
$normalizedDir = Join-Path $repoRoot "exports\trading-mvp\normalized"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"

New-Item -ItemType Directory -Force -Path $normalizedDir, $backtestDir, $runDir | Out-Null
Set-Location $repoRoot

if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE") {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume or reject the incomplete run before WS slice postprocess."
    }
}

if (-not $GapAuditPath) {
    $latest = Get-ChildItem -LiteralPath $backtestDir -Filter "ws_gap_audit_*.json" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        $GapAuditPath = $latest.FullName
    }
}
if (-not $GapAuditPath) {
    throw "GapAuditPath is required."
}
$GapAuditPath = (Resolve-Path -LiteralPath $GapAuditPath).Path
$gapAudit = Get-Content -Raw -LiteralPath $GapAuditPath | ConvertFrom-Json

if (-not $InputPath -and $gapAudit.input) {
    $InputPath = [string]$gapAudit.input
}
if (-not $InputPath) {
    throw "InputPath is required or must be present in gap audit artifact."
}
$InputPath = (Resolve-Path -LiteralPath $InputPath).Path

if (($StartTs -le 0 -or $EndTs -le 0) -and $gapAudit.clean_windows) {
    $windows = @($gapAudit.clean_windows)
    if ($CleanWindowIndex -lt 0 -or $CleanWindowIndex -ge $windows.Count) {
        throw "CleanWindowIndex $CleanWindowIndex is out of range. clean_windows=$($windows.Count)"
    }
    $window = $windows[$CleanWindowIndex]
    $StartTs = [double]$window.start_ts
    $EndTs = [double]$window.end_ts
}
if ($StartTs -le 0 -or $EndTs -le 0 -or $EndTs -le $StartTs) {
    throw "Valid StartTs and EndTs are required."
}

if ($PostprocessPath) {
    $PostprocessPath = (Resolve-Path -LiteralPath $PostprocessPath).Path
    if (-not $SourceManifestPath) {
        $sourcePostprocess = Get-Content -Raw -LiteralPath $PostprocessPath | ConvertFrom-Json
        if ($sourcePostprocess.manifest) {
            $SourceManifestPath = [string]$sourcePostprocess.manifest
        }
    }
}
if ($SourceManifestPath) {
    $SourceManifestPath = (Resolve-Path -LiteralPath $SourceManifestPath).Path
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$label = if ($RunLabel) { $RunLabel } else { "ws_clean_slice_{0}" -f $stamp }
$normalizedOutput = Join-Path $normalizedDir ("ws_normalized_{0}.jsonl" -f $label)
$sliceManifest = Join-Path $backtestDir ("ws_slice_manifest_{0}.json" -f $label)
$qualityOutput = Join-Path $backtestDir ("ws_data_quality_{0}.json" -f $label)
$postprocessOutput = Join-Path $backtestDir ("ws_postprocess_{0}.json" -f $label)
$consoleLog = Join-Path $runDir ("ws_slice_postprocess_{0}.console.log" -f $label)
$progressLog = Join-Path $runDir ("ws_slice_postprocess_{0}.progress.jsonl" -f $label)
$stdoutLog = Join-Path $runDir ("ws_slice_postprocess_{0}.stdout.log" -f $label)
$stderrLog = Join-Path $runDir ("ws_slice_postprocess_{0}.stderr.log" -f $label)

$pythonCandidates = @(
    $env:TRADING_MVP_PYTHON,
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
    "C:\Program Files\Python313\python.exe",
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
    mode = "ws_slice_postprocess_visible_plan"
    ok = $true
    would_run = (-not [bool]$PlanOnly)
    input = $InputPath
    gap_audit = $GapAuditPath
    source_postprocess = $PostprocessPath
    source_manifest = $SourceManifestPath
    start_ts = $StartTs
    end_ts = $EndTs
    duration_hours = ($EndTs - $StartTs) / 3600.0
    normalized_output = $normalizedOutput
    slice_manifest = $sliceManifest
    quality_output = $qualityOutput
    postprocess_output = $postprocessOutput
    console_log = $consoleLog
    progress_log = $progressLog
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    blocked_actions = @("live_orders", "api_keys", "leverage_or_margin", "replay_grid_if_slice_data_quality_rejected")
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

$argsList = @(
    $script,
    "--input", $InputPath,
    "--start-ts", ([string]$StartTs),
    "--end-ts", ([string]$EndTs),
    "--normalized-output", $normalizedOutput,
    "--manifest-output", $sliceManifest,
    "--quality-output", $qualityOutput,
    "--postprocess-output", $postprocessOutput,
    "--source-gap-audit", $GapAuditPath,
    "--progress-every-lines", "1000000",
    "--progress-file", $progressLog,
    "--print-progress"
)
if ($PostprocessPath) {
    $argsList += @("--source-postprocess", $PostprocessPath)
}
if ($SourceManifestPath) {
    $argsList += @("--source-manifest", $SourceManifestPath)
}

Write-Host "Starting visible WS slice postprocess"
Write-Host "Input: $InputPath"
Write-Host "Window: $StartTs -> $EndTs ($([math]::Round(($EndTs - $StartTs) / 3600.0, 2)) h)"
Write-Host "Normalized: $normalizedOutput"
Write-Host "Postprocess: $postprocessOutput"
Write-Host "Progress: $progressLog"

$transcriptStarted = $false
try {
    Start-Transcript -Path $consoleLog -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

try {
    "stderr is merged into stdout for inline visible execution. See $stdoutLog" | Set-Content -LiteralPath $stderrLog -Encoding UTF8
    Write-Host "Worker mode: inline visible python"
    & $python @argsList 2>&1 | Tee-Object -FilePath $stdoutLog
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $stdoutTail = if (Test-Path -LiteralPath $stdoutLog) { Get-Content -LiteralPath $stdoutLog -Tail 20 } else { @() }
        throw "ws-slice-postprocess failed with exit code $exitCode. output tail: $($stdoutTail -join ' | ')"
    }
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $postprocessOutput)) {
    throw "Expected slice postprocess artifact was not created: $postprocessOutput"
}

$result = Get-Content -Raw -LiteralPath $postprocessOutput | ConvertFrom-Json
Write-Host ("Replay allowed: {0}" -f ([bool]$result.replay_allowed))
Write-Host ("Rows written: {0}" -f $result.normalization.rows_written)
Write-Host ("Data-quality reasons: {0}" -f (@($result.data_quality.reasons) -join ","))

if (-not $NoPause) {
    Read-Host "Press Enter to close this slice-postprocess window"
}
