param(
    [int]$TotalSec = 7200,
    [int]$SegmentSec = 3600,
    [string]$Exchanges = "mexc,gateio",
    [string]$UniversePath = "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv",
    [int]$MaxSymbols = 300,
    [int]$MaxPairsPerExchange = 16,
    [string]$Quote = "USDT",
    [ValidateSet("100ms","10ms")]
    [string]$UpdateInterval = "100ms",
    [string]$RunId = "",
    [string]$Symbols = "",
    [string]$PythonExe = "",
    [int]$EarlyDensityCheckAfterMinutes = 60,
    [double]$EarlyDensityMinLinesPerMinute = 10.0,
    [int]$EarlyDensityMinRawLines = 600,
    [int]$EarlyDensityMinRawFiles = 1,
    [switch]$DisableEarlyDensityGuard,
    [int]$ZeroLineAbortAfterMinutes = 10,
    [switch]$DisableZeroLineAbort,
    [int]$SchemaProbeAfterMinutes = 1,
    [int]$SchemaProbeMaxLines = 20,
    [switch]$DisableSchemaProbe,
    [switch]$Resume,
    [switch]$ReplaceStoppedIncomplete,
    [switch]$ConfirmedLongRun,
    [switch]$PlanOnly,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configPath = Join-Path $repoRoot "trading_mvp\config.json"
$collectorPy = Join-Path $repoRoot "trading_mvp\src\ws_durable_collector.py"
$durableRoot = Join-Path $repoRoot "exports\trading-mvp\raw-durable"
$runRoot = Join-Path $repoRoot "exports\trading-mvp\run"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$archivedGateDir = Join-Path $repoRoot "docs\agent-log\archived-gates"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$edgePreflight = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"
$wsCollectReadiness = Join-Path $repoRoot "tools\trading_ws_collect_readiness.ps1"
$wsPostprocess = Join-Path $repoRoot "tools\run_ws_postprocess_visible.ps1"
$wsReplayValidation = Join-Path $repoRoot "tools\run_ws_replay_validation_visible.ps1"

function Resolve-RepoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function ConvertTo-JsonFile {
    param(
        [string]$Path,
        [object]$Payload,
        [int]$Depth = 12
    )
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth $Depth | Set-Content -Encoding UTF8 -LiteralPath $Path
}

function Quote-Arg {
    param([string]$Value)
    if ($null -eq $Value) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Join-CommandLine {
    param([string[]]$Parts)
    return (($Parts | ForEach-Object { Quote-Arg -Value $_ }) -join " ")
}

function Test-PythonWithRequests {
    param([string]$Path)
    $result = [ordered]@{
        path = $Path
        executable = ""
        ok = $false
        error = ""
    }
    try {
        $cmd = Get-Command $Path -ErrorAction SilentlyContinue
        $resolved = if ($cmd) { $cmd.Source } else { $Path }
        if (-not (Test-Path -LiteralPath $resolved)) {
            $result.error = "not found"
            return [pscustomobject]$result
        }
        $probe = & $resolved -c "import requests, sys; print(sys.executable)" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $result.error = ($probe | Out-String).Trim()
            return [pscustomobject]$result
        }
        $result.executable = [string](@($probe)[0])
        $result.ok = $true
    } catch {
        $result.error = $_.Exception.Message
    }
    return [pscustomobject]$result
}

function Resolve-PythonExe {
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @(
        $PythonExe,
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and -not $candidates.Contains($candidate)) {
            $candidates.Add($candidate) | Out-Null
        }
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and -not $candidates.Contains($pythonCommand.Source)) {
        $candidates.Add($pythonCommand.Source) | Out-Null
    }
    $results = @($candidates | ForEach-Object { Test-PythonWithRequests -Path $_ })
    $selected = $results | Where-Object { $_.ok } | Select-Object -First 1
    return [pscustomobject]@{
        selected = if ($selected) { [string]$selected.executable } else { "" }
        candidates = $results
    }
}

function Get-ActiveGateStatus {
    if (-not (Test-Path -LiteralPath $gatePath)) {
        return $null
    }
    try {
        return & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            status = "GATE_CHECK_FAILED"
            warning = $_.Exception.Message
        }
    }
}

function Read-JsonOrNull {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-WsRawSchema {
    param(
        [object[]]$Files,
        [int]$MaxLines = 20
    )
    $required = @("recv_ts", "exchange", "event_type", "channel", "symbol", "payload")
    $checked = 0
    foreach ($file in @($Files)) {
        if (-not $file -or -not (Test-Path -LiteralPath $file.FullName)) {
            continue
        }
        $lines = @(Get-Content -LiteralPath $file.FullName -TotalCount $MaxLines -ErrorAction SilentlyContinue)
        foreach ($line in $lines) {
            if (-not $line) {
                continue
            }
            $checked += 1
            try {
                $row = $line | ConvertFrom-Json
            } catch {
                return [pscustomobject]@{
                    ready = $true
                    ok = $false
                    reason = "invalid_json"
                    checked_lines = $checked
                    sample_path = $file.FullName
                    error = $_.Exception.Message
                }
            }
            $names = @($row.PSObject.Properties.Name)
            $missing = @($required | Where-Object { $names -notcontains $_ })
            if ($missing.Count -gt 0) {
                return [pscustomobject]@{
                    ready = $true
                    ok = $false
                    reason = "missing_required_fields"
                    checked_lines = $checked
                    sample_path = $file.FullName
                    missing_fields = $missing
                }
            }
        }
        if ($checked -ge $MaxLines) {
            break
        }
    }
    if ($checked -eq 0) {
        return [pscustomobject]@{
            ready = $false
            ok = $false
            reason = "no_raw_lines_to_probe"
            checked_lines = 0
        }
    }
    return [pscustomObject]@{
        ready = $true
        ok = $true
        reason = "schema_probe_passed"
        checked_lines = $checked
    }
}

function Get-RawFiles {
    param([string]$RunDir)
    if (-not (Test-Path -LiteralPath $RunDir)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $RunDir -Recurse -Filter "ws_*.jsonl" -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch "\\seg_\d{3}_incomplete_" }
    )
}

function Get-LineCount {
    param([object[]]$Files)
    $count = 0
    foreach ($file in @($Files)) {
        try {
            $count += (Get-Content -LiteralPath $file.FullName | Measure-Object -Line).Lines
        } catch {}
    }
    return [int64]$count
}

function Stop-ChildProcess {
    param(
        [object]$Process,
        [string]$Reason
    )
    Write-Host "Stopping collector: $Reason" -ForegroundColor Yellow
    try {
        Stop-Process -Id $Process.Id -Force -ErrorAction Stop
    } catch {
        Write-Host ("Stop-Process failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
}

function New-RunId {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $hours = [Math]::Round($TotalSec / 3600.0, 2).ToString("0.##", [System.Globalization.CultureInfo]::InvariantCulture)
    return "ws_durable_${hours}h_$stamp"
}

function Get-ResumeCommand {
    param([string]$Id)
    return "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -RunId `"$Id`" -Resume -ConfirmedLongRun"
}

function Get-StatusCommand {
    param([string]$Dir)
    return "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\watch_ws_collect_durable.ps1`" -RunDir `"$Dir`""
}

function Write-StoppedAlert {
    param(
        [string]$RunDir,
        [string]$Reason,
        [string]$ResumeCommand,
        [string]$StatusCommand
    )
    $alertPath = Join-Path $RunDir "STOPPED_INCOMPLETE.txt"
    @(
        "Durable WS collect stopped incomplete.",
        "reason=$Reason",
        "run_dir=$RunDir",
        "resume=$ResumeCommand",
        "status=$StatusCommand",
        "created_at=$(Get-Date -Format o)"
    ) | Set-Content -Encoding UTF8 -LiteralPath $alertPath
    return $alertPath
}

function Set-JsonProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )
    if ($null -ne $Object.PSObject.Properties[$Name]) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Archive-StoppedGateForReplacement {
    param([string]$NewRunId)
    if (-not (Test-Path -LiteralPath $gatePath)) {
        return $null
    }
    $old = Read-JsonOrNull -Path $gatePath
    if (-not $old -or [string]$old.status -ne "STOPPED_INCOMPLETE") {
        return $null
    }
    New-Item -ItemType Directory -Force -Path $archivedGateDir | Out-Null
    $safeOldRunId = ([string]$old.run_id) -replace '[^\w.-]', '_'
    $archivePath = Join-Path $archivedGateDir ("{0}_replaced_by_{1}_{2}.json" -f $safeOldRunId, $NewRunId, (Get-Date -Format "yyyyMMdd_HHmmss"))
    Copy-Item -LiteralPath $gatePath -Destination $archivePath -Force
    $neutralGate = [ordered]@{
        schema = "active_run_gate_v1"
        project = "trading_mvp"
        run_id = "archived_stopped_incomplete_before_$NewRunId"
        status = "READY_FOR_POSTPROCESS"
        final = $true
        replay_allowed = $false
        created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        archived_replaced_gate = $archivePath
        replaced_gate_run_id = [string]$old.run_id
        replacement_run_id = $NewRunId
        next_goal_decision = "START_DURABLE_WS_VERIFICATION_AFTER_REJECTING_STOPPED_INCOMPLETE"
        next_goal_reason = "Prior stopped incomplete dataset was archived before an explicitly confirmed durable replacement run."
    }
    ConvertTo-JsonFile -Path $gatePath -Payload $neutralGate -Depth 8
    return $archivePath
}

if ($TotalSec -le 0) {
    throw "TotalSec must be > 0"
}
if ($SegmentSec -le 0) {
    throw "SegmentSec must be > 0"
}
if ($SegmentSec -gt $TotalSec) {
    throw "SegmentSec cannot exceed TotalSec"
}
if (-not $PlanOnly -and -not $ConfirmedLongRun) {
    throw "Explicit run confirmation is required. Use -PlanOnly or re-run with -ConfirmedLongRun after explicit user approval."
}

New-Item -ItemType Directory -Force -Path $durableRoot, $runRoot, (Split-Path -Parent $gatePath) | Out-Null
$resolvedUniversePath = Resolve-RepoPath -Path $UniversePath
$gateStatus = Get-ActiveGateStatus
$gateStatusText = if ($gateStatus) { [string]$gateStatus.status } else { "NO_GATE" }
$effectiveRunId = if ($RunId) { $RunId } else { New-RunId }
$runDir = Join-Path $durableRoot $effectiveRunId
$statePath = Join-Path $runDir "state.json"
$stitchedManifest = Join-Path $runDir ("ws_collect_{0}.json" -f $effectiveRunId)
$stdoutLog = Join-Path $runDir "collector.stdout.log"
$stderrLog = Join-Path $runDir "collector.stderr.log"
$launchPath = Join-Path $runDir "launch.json"
$resumeCommand = Get-ResumeCommand -Id $effectiveRunId
$statusCommand = Get-StatusCommand -Dir $runDir
$postprocessPlaceholder = "<exports\trading-mvp\backtests\ws_postprocess_*.json>"
$postprocessCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$wsPostprocess`" -ManifestPath `"$stitchedManifest`""
$replayPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$wsReplayValidation`" -PostprocessPath $postprocessPlaceholder -ExpectedManifestPath `"$stitchedManifest`" -PlanOnly"

$selfPreflightGuard = [ordered]@{
    enabled = $true
    script = $edgePreflight
    required_status = "READY_FOR_EDGE_PROOF_STEP"
    required_check = "current_scorecard_freshness"
    action = "refuse_confirmed_long_run_before_start"
}
$readinessGuard = [ordered]@{
    enabled = ($TotalSec -ge 86400)
    script = $wsCollectReadiness
    required_status = "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION"
    required_ok = $true
    action = if ($TotalSec -ge 86400) { "refuse_confirmed_long_run_before_start" } else { "skipped_for_short_verification_run" }
}
$earlyDensityGuard = [ordered]@{
    enabled = (-not [bool]$DisableEarlyDensityGuard)
    check_after_minutes = $EarlyDensityCheckAfterMinutes
    min_lines_per_minute = $EarlyDensityMinLinesPerMinute
    min_raw_lines = $EarlyDensityMinRawLines
    min_raw_files = $EarlyDensityMinRawFiles
    action = "stop_child_collector_finalize_and_mark_stopped_incomplete"
}
$zeroLineGuard = [ordered]@{
    enabled = (-not [bool]$DisableZeroLineAbort)
    abort_after_minutes = $ZeroLineAbortAfterMinutes
    min_raw_lines = 1
    action = "stop_child_collector_finalize_and_mark_stopped_incomplete"
}
$schemaProbe = [ordered]@{
    enabled = (-not [bool]$DisableSchemaProbe)
    check_after_minutes = $SchemaProbeAfterMinutes
    max_lines = $SchemaProbeMaxLines
    required_fields = @("recv_ts", "exchange", "event_type", "channel", "symbol", "payload")
    action = "stop_child_collector_finalize_and_mark_stopped_incomplete_on_invalid_raw_jsonl"
}

$approvalArgs = @(
    "-TotalSec", [string]$TotalSec,
    "-SegmentSec", [string]$SegmentSec,
    "-Exchanges", $Exchanges,
    "-UniversePath", $resolvedUniversePath,
    "-MaxSymbols", [string]$MaxSymbols,
    "-MaxPairsPerExchange", [string]$MaxPairsPerExchange,
    "-UpdateInterval", $UpdateInterval,
    "-ConfirmedLongRun"
)
if ($gateStatusText -eq "STOPPED_INCOMPLETE" -and -not $Resume) {
    $approvalArgs += "-ReplaceStoppedIncomplete"
}
$approvalCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" " + (Join-CommandLine -Parts $approvalArgs)

if ($PlanOnly) {
    $pythonProbe = Resolve-PythonExe
    $plan = [ordered]@{
        mode = "ws_collect_durable_plan"
        would_start = $false
        requires_confirmed_long_run = $true
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        total_sec = $TotalSec
        segment_sec = $SegmentSec
        segments_planned = [Math]::Ceiling($TotalSec / [double]$SegmentSec)
        exchanges = $Exchanges
        universe_path = $resolvedUniversePath
        max_symbols = $MaxSymbols
        max_pairs_per_exchange = $MaxPairsPerExchange
        update_interval = $UpdateInterval
        gate_status = $gateStatusText
        replace_stopped_incomplete_available = ($gateStatusText -eq "STOPPED_INCOMPLETE")
        run_id_preview = $effectiveRunId
        run_dir_preview = $runDir
        state_path = $statePath
        stitched_manifest_path = $stitchedManifest
        selected_python = $pythonProbe.selected
        self_preflight_guard = $selfPreflightGuard
        readiness_guard = $readinessGuard
        early_density_guard = $earlyDensityGuard
        zero_line_guard = $zeroLineGuard
        schema_probe = $schemaProbe
        notification_policy = [ordered]@{
            stopped_alert_file = (Join-Path $runDir "STOPPED_INCOMPLETE.txt")
            gate_notification_required = $true
            stale_heartbeat_is_stop_signal = $true
        }
        resume_command = $resumeCommand
        status_command = $statusCommand
        command_after_explicit_approval = $approvalCommand
        postprocess_command_after_ready = $postprocessCommand
        replay_validation_plan_after_postprocess = $replayPlanCommand
    }
    $plan | ConvertTo-Json -Depth 12
    exit 0
}

if ($gateStatusText -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
}
if ($gateStatusText -eq "STOPPED_INCOMPLETE" -and -not $Resume -and -not $ReplaceStoppedIncomplete) {
    throw "Active run gate is STOPPED_INCOMPLETE. Use -Resume for the same durable run or -ReplaceStoppedIncomplete to explicitly archive the old incomplete dataset before starting a replacement run."
}
if ($Resume -and -not $RunId) {
    throw "Resume requires -RunId so the console can continue an exact durable run directory."
}

$pythonProbeActual = Resolve-PythonExe
if (-not $pythonProbeActual.selected) {
    throw "No Python candidate with requests was found. Set TRADING_MVP_PYTHON or pass -PythonExe."
}
$python = [string]$pythonProbeActual.selected

$archivedGatePath = $null
try {
    if ($ReplaceStoppedIncomplete -and -not $Resume) {
        $archivedGatePath = Archive-StoppedGateForReplacement -NewRunId $effectiveRunId
    }

    if (-not $Resume) {
        if (-not (Test-Path -LiteralPath $edgePreflight)) {
            throw "Missing preflight script: $edgePreflight"
        }
        $preflight = & pwsh -NoProfile -ExecutionPolicy Bypass -File $edgePreflight -Json | ConvertFrom-Json
        $preflightChecks = @($preflight.checks)
        $freshnessCheck = $preflightChecks | Where-Object { $_.name -eq "current_scorecard_freshness" } | Select-Object -First 1
        if (-not [bool]$preflight.ok) {
            throw "Preflight refused durable collect: ok=false status=$($preflight.status) fail_count=$($preflight.fail_count)."
        }
        if ([string]$preflight.status -ne "READY_FOR_EDGE_PROOF_STEP") {
            throw "Preflight refused durable collect: status=$($preflight.status), expected READY_FOR_EDGE_PROOF_STEP."
        }
        if (-not $freshnessCheck -or [string]$freshnessCheck.status -ne "pass") {
            throw "Preflight refused durable collect: current_scorecard_freshness did not pass."
        }
        $selfPreflightGuard.preflight_status = $preflight.status
        $selfPreflightGuard.preflight_generated_at = $preflight.generated_at
        $selfPreflightGuard.current_scorecard = $preflight.current_scorecard

        if ($TotalSec -ge 86400) {
            $readiness = & pwsh -NoProfile -ExecutionPolicy Bypass -File $wsCollectReadiness -Hours ($TotalSec / 3600.0) -MaxPairsPerExchange $MaxPairsPerExchange -UniversePath $resolvedUniversePath -Json | ConvertFrom-Json
            if (-not [bool]$readiness.ok) {
                throw "Readiness refused durable collect: status=$($readiness.status) fail_count=$($readiness.fail_count)."
            }
            $readinessGuard.readiness_status = $readiness.status
            $readinessGuard.readiness_generated_at = $readiness.generated_at
            $readinessGuard.readiness_output_path = $readiness.output_path
        }
    }
} catch {
    if ($archivedGatePath -and (Test-Path -LiteralPath $archivedGatePath)) {
        Copy-Item -LiteralPath $archivedGatePath -Destination $gatePath -Force
    }
    throw
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$symbolsArg = $Symbols
$symbolPlan = $null
if ($Resume) {
    $priorLaunch = Read-JsonOrNull -Path $launchPath
    if (-not $symbolsArg -and $priorLaunch -and $priorLaunch.symbols_arg) {
        $symbolsArg = [string]$priorLaunch.symbols_arg
    }
}
if (-not $symbolsArg) {
    $planOutput = & $python $collectorPy plan-symbols --config $configPath --exchanges $Exchanges --universe $resolvedUniversePath --quote $Quote --max-symbols $MaxSymbols --max-pairs-per-exchange $MaxPairsPerExchange
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve durable WS symbols."
    }
    $symbolPlan = ($planOutput | Out-String) | ConvertFrom-Json
    $symbolsArg = [string]$symbolPlan.symbols_arg
}

$collectorArgs = @(
    $collectorPy,
    "collect",
    "--symbols", $symbolsArg,
    "--out-dir", $durableRoot,
    "--run-id", $effectiveRunId,
    "--total-sec", [string]$TotalSec,
    "--segment-sec", [string]$SegmentSec,
    "--update-interval", $UpdateInterval
)
if ($Resume) {
    $collectorArgs += "--resume"
}

$launchInfo = [ordered]@{
    schema = "ws_durable_launch_v2"
    run_id = $effectiveRunId
    run_dir = $runDir
    started_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    resumed = [bool]$Resume
    replaced_stopped_incomplete_gate = [bool]$ReplaceStoppedIncomplete
    archived_replaced_gate = $archivedGatePath
    command = Join-CommandLine -Parts (@($python) + $collectorArgs)
    cwd = $repoRoot
    python = $python
    collector_script = $collectorPy
    symbols_arg = $symbolsArg
    symbol_plan = $symbolPlan
    total_sec = $TotalSec
    segment_sec = $SegmentSec
    expected_end = (Get-Date).AddSeconds($TotalSec).ToString("yyyy-MM-ddTHH:mm:sszzz")
    state_file = $statePath
    stitched_manifest = $stitchedManifest
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    status_command = $statusCommand
    resume_command = $resumeCommand
    postprocess_command_after_ready = $postprocessCommand
}
ConvertTo-JsonFile -Path $launchPath -Payload $launchInfo -Depth 12

$gate = [ordered]@{
    schema = "active_run_gate_v1"
    project = "trading_mvp"
    run_id = $effectiveRunId
    status = "RUNNING"
    created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    purpose = "Visible monitored durable segmented WS collect; each completed segment has its own manifest and the run can be resumed from console."
    blocking_rule = "While status is RUNNING, do not run postprocess, grid/search, code changes, broad analysis, or new collectors. Only status/ETA checks are allowed."
    monitor_pid = $PID
    process_ids = @($PID)
    monitor_script = $PSCommandPath
    output_path = $runDir
    manifest_path = $stitchedManifest
    state_path = $statePath
    launch_path = $launchPath
    duration_sec = $TotalSec
    total_sec = $TotalSec
    segment_sec = $SegmentSec
    exchanges = $Exchanges
    max_symbols = $MaxSymbols
    max_pairs_per_exchange = $MaxPairsPerExchange
    universe_path = $resolvedUniversePath
    update_interval = $UpdateInterval
    resume = [bool]$Resume
    resume_command = $resumeCommand
    status_check_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
    durable_status_command = $statusCommand
    notification_required = $false
    self_preflight_guard = $selfPreflightGuard
    readiness_guard = $readinessGuard
    early_density_guard = $earlyDensityGuard
    zero_line_guard = $zeroLineGuard
    schema_probe = $schemaProbe
    postprocess_command_after_ready = $postprocessCommand
    replay_validation_plan_after_postprocess = $replayPlanCommand
    next_step_after_ready = "Run guarded ws-postprocess with the completed durable stitched manifest: $postprocessCommand. Then run replay validation PlanOnly with the same manifest: $replayPlanCommand. Do not treat as investment advice or accepted strategy."
}
ConvertTo-JsonFile -Path $gatePath -Payload $gate -Depth 10

Write-Host "Starting visible durable WS collect" -ForegroundColor Cyan
Write-Host "Run id: $effectiveRunId"
Write-Host "Run dir: $runDir"
Write-Host "State: $statePath"
Write-Host "Stitched manifest: $stitchedManifest"
Write-Host "Resume command: $resumeCommand"
Write-Host "Status command: $statusCommand"
Write-Host "Collector command: $($launchInfo.command)"

$proc = Start-Process -FilePath $python -ArgumentList $collectorArgs -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
$gate.process_ids = @($PID, $proc.Id)
ConvertTo-JsonFile -Path $gatePath -Payload $gate -Depth 10
Write-Host "Collector PID: $($proc.Id)"

$startedAt = Get-Date
$zeroLineChecked = $false
$zeroLineRejected = $false
$zeroLineResult = $null
$schemaProbeChecked = $false
$schemaProbeRejected = $false
$schemaProbeResult = $null
$earlyDensityChecked = $false
$earlyDensityRejected = $false
$earlyDensityResult = $null
$lastLineCount = 0

while (-not $proc.HasExited) {
    try {
        $state = Read-JsonOrNull -Path $statePath
        $rawFiles = @(Get-RawFiles -RunDir $runDir)
        $rawBytes = 0
        foreach ($file in $rawFiles) {
            $rawBytes += [int64]$file.Length
        }
        $elapsedMinutes = [Math]::Max(0.001, ((Get-Date) - $startedAt).TotalMinutes)
        $hbAge = $null
        if ($state -and $state.heartbeat_epoch) {
            $hbAge = [Math]::Round(([DateTimeOffset]::Now.ToUnixTimeSeconds() - [double]$state.heartbeat_epoch), 0)
        }
        Write-Host ("[{0}] pid={1} state={2} seg={3}/{4} raw_files={5} raw_mb={6} hb_age={7}s" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id, $(if ($state) { $state.status } else { "no_state" }), $(if ($state) { $state.segment_index } else { "?" }), $(if ($state) { $state.segments_planned } else { "?" }), $rawFiles.Count, [Math]::Round($rawBytes / 1MB, 1), $(if ($null -ne $hbAge) { $hbAge } else { "?" }))

        if ((-not $DisableZeroLineAbort) -and (-not $zeroLineChecked) -and ($elapsedMinutes -ge $ZeroLineAbortAfterMinutes)) {
            $zeroLineChecked = $true
            $rawLineCount = Get-LineCount -Files $rawFiles
            $lastLineCount = $rawLineCount
            $zeroLineResult = [pscustomobject]@{
                checked_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
                elapsed_minutes = [Math]::Round($elapsedMinutes, 2)
                raw_files = $rawFiles.Count
                raw_lines = $rawLineCount
                min_raw_lines = 1
                ok = ($rawLineCount -gt 0)
            }
            Write-Host ("Zero-line guard: ok={0}; raw_files={1}; raw_lines={2}" -f $zeroLineResult.ok, $zeroLineResult.raw_files, $zeroLineResult.raw_lines)
            if (-not [bool]$zeroLineResult.ok) {
                $zeroLineRejected = $true
                Stop-ChildProcess -Process $proc -Reason "zero_line_guard_failed"
                break
            }
        }

        if ((-not $DisableSchemaProbe) -and (-not $schemaProbeChecked) -and ($elapsedMinutes -ge $SchemaProbeAfterMinutes) -and ($rawFiles.Count -gt 0)) {
            $schemaProbeResult = Test-WsRawSchema -Files $rawFiles -MaxLines $SchemaProbeMaxLines
            if ($schemaProbeResult.ready) {
                $schemaProbeChecked = $true
                Write-Host ("Schema probe: ok={0}; reason={1}; checked_lines={2}" -f $schemaProbeResult.ok, $schemaProbeResult.reason, $schemaProbeResult.checked_lines)
                if (-not [bool]$schemaProbeResult.ok) {
                    $schemaProbeRejected = $true
                    Stop-ChildProcess -Process $proc -Reason "schema_probe_failed"
                    break
                }
            }
        }

        if ((-not $DisableEarlyDensityGuard) -and (-not $earlyDensityChecked) -and ($elapsedMinutes -ge $EarlyDensityCheckAfterMinutes)) {
            $earlyDensityChecked = $true
            $rawLineCount = Get-LineCount -Files $rawFiles
            $lastLineCount = $rawLineCount
            $linesPerMinute = [Math]::Round($rawLineCount / $elapsedMinutes, 2)
            $earlyDensityResult = [pscustomobject]@{
                checked_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
                elapsed_minutes = [Math]::Round($elapsedMinutes, 2)
                raw_files = $rawFiles.Count
                raw_lines = $rawLineCount
                lines_per_minute = $linesPerMinute
                min_raw_files = $EarlyDensityMinRawFiles
                min_raw_lines = $EarlyDensityMinRawLines
                min_lines_per_minute = $EarlyDensityMinLinesPerMinute
                ok = (($rawFiles.Count -ge $EarlyDensityMinRawFiles) -and ($rawLineCount -ge $EarlyDensityMinRawLines) -and ($linesPerMinute -ge $EarlyDensityMinLinesPerMinute))
            }
            Write-Host ("Early density guard: ok={0}; raw_files={1}; raw_lines={2}; lines_per_min={3}" -f $earlyDensityResult.ok, $earlyDensityResult.raw_files, $earlyDensityResult.raw_lines, $earlyDensityResult.lines_per_minute)
            if (-not [bool]$earlyDensityResult.ok) {
                $earlyDensityRejected = $true
                Stop-ChildProcess -Process $proc -Reason "early_density_guard_failed"
                break
            }
        }

        if ((Test-Path -LiteralPath $stderrLog) -and (Get-Item -LiteralPath $stderrLog).Length -gt 0) {
            Write-Host "--- stderr tail ---"
            Get-Content -LiteralPath $stderrLog -Tail 5
            Write-Host "--- end stderr tail ---"
        }
    } catch {
        Write-Host ("monitor error: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 60
    try { $proc.Refresh() } catch {}
}

try { $proc.Refresh() } catch {}
Write-Host "Collector exited. ExitCode=$($proc.ExitCode)"

try {
    & $python $collectorPy finalize --run-dir $runDir --expected-total-sec $TotalSec | Out-Null
} catch {
    Write-Host ("Finalize failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
}

$manifest = Read-JsonOrNull -Path $stitchedManifest
$manifestCompleted = ($manifest -and [bool]$manifest.completed -and [bool]$manifest.final)
$guardRejected = $zeroLineRejected -or $schemaProbeRejected -or $earlyDensityRejected
$finalStatus = if (($proc.ExitCode -eq 0) -and $manifestCompleted -and -not $guardRejected) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
$stopReason = if ($zeroLineRejected) {
    "zero_line_guard_failed"
} elseif ($schemaProbeRejected) {
    "schema_probe_failed"
} elseif ($earlyDensityRejected) {
    "early_density_guard_failed"
} elseif ($manifest) {
    [string]$manifest.stop_condition
} else {
    "missing_stitched_manifest"
}

$alertPath = $null
if ($finalStatus -eq "STOPPED_INCOMPLETE") {
    $alertPath = Write-StoppedAlert -RunDir $runDir -Reason $stopReason -ResumeCommand $resumeCommand -StatusCommand $statusCommand
}

$updatedGate = Read-JsonOrNull -Path $gatePath
if (-not $updatedGate) {
    $updatedGate = [pscustomobject]$gate
}
Set-JsonProperty -Object $updatedGate -Name "status" -Value $finalStatus
Set-JsonProperty -Object $updatedGate -Name "updated_at" -Value (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
Set-JsonProperty -Object $updatedGate -Name "process_ids" -Value @()
Set-JsonProperty -Object $updatedGate -Name "manifest_path" -Value $stitchedManifest
Set-JsonProperty -Object $updatedGate -Name "output_path" -Value $runDir
Set-JsonProperty -Object $updatedGate -Name "state_path" -Value $statePath
Set-JsonProperty -Object $updatedGate -Name "final" -Value $(if ($manifest) { [bool]$manifest.final } else { $false })
Set-JsonProperty -Object $updatedGate -Name "stop_reason" -Value $stopReason
Set-JsonProperty -Object $updatedGate -Name "requested_duration_sec" -Value $(if ($manifest) { $manifest.requested_duration_sec } else { $TotalSec })
Set-JsonProperty -Object $updatedGate -Name "actual_duration_sec" -Value $(if ($manifest) { $manifest.actual_duration_sec } else { $null })
Set-JsonProperty -Object $updatedGate -Name "total_events" -Value $(if ($manifest) { $manifest.total_events } else { $null })
Set-JsonProperty -Object $updatedGate -Name "rows" -Value $(if ($manifest) { $manifest.total_events } else { 0 })
Set-JsonProperty -Object $updatedGate -Name "coverage_ratio" -Value $(if ($manifest) { $manifest.coverage_ratio } else { $null })
Set-JsonProperty -Object $updatedGate -Name "notification_required" -Value ($finalStatus -eq "STOPPED_INCOMPLETE")
Set-JsonProperty -Object $updatedGate -Name "alert_path" -Value $alertPath
Set-JsonProperty -Object $updatedGate -Name "resume_command" -Value $resumeCommand
Set-JsonProperty -Object $updatedGate -Name "durable_status_command" -Value $statusCommand
Set-JsonProperty -Object $updatedGate -Name "early_density_guard_result" -Value $earlyDensityResult
Set-JsonProperty -Object $updatedGate -Name "zero_line_guard_result" -Value $zeroLineResult
Set-JsonProperty -Object $updatedGate -Name "schema_probe_result" -Value $schemaProbeResult
ConvertTo-JsonFile -Path $gatePath -Payload $updatedGate -Depth 12

if ((Test-Path -LiteralPath $stdoutLog) -and (Get-Item -LiteralPath $stdoutLog).Length -gt 0) {
    Write-Host "--- stdout tail ---"
    Get-Content -LiteralPath $stdoutLog -Tail 20
}
if ((Test-Path -LiteralPath $stderrLog) -and (Get-Item -LiteralPath $stderrLog).Length -gt 0) {
    Write-Host "--- stderr tail ---"
    Get-Content -LiteralPath $stderrLog -Tail 20
}

if ($finalStatus -eq "READY_FOR_POSTPROCESS") {
    Write-Host "Durable collect completed: READY_FOR_POSTPROCESS" -ForegroundColor Green
    Write-Host "Next: $postprocessCommand"
} else {
    Write-Host "Durable collect stopped incomplete: $stopReason" -ForegroundColor Yellow
    Write-Host "Alert: $alertPath"
    Write-Host "Resume from console:"
    Write-Host "  $resumeCommand"
}

if (-not $NoPause) {
    Read-Host "Press Enter to close this monitor"
}

if ($finalStatus -eq "READY_FOR_POSTPROCESS") {
    exit 0
}
exit 1
