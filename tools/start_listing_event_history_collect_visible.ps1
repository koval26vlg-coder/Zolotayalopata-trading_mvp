param(
    [string]$ApprovalPacketPath = "exports\trading-mvp\analysis\listing_event_history_collect_approval_packet_current.json",
    [string]$PreviewPath = "",
    [int]$MaxEvents = 0,
    [int]$CandlesPerRequest = 1000,
    [double]$SleepSec = 0.5,
    [int]$TimeoutSec = 15,
    [int]$MaxRetries = 2,
    [int]$ProgressEvery = 10,
    [switch]$ConfirmedListingHistoryCollect,
    [switch]$PlanOnly,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$approvalPacketScript = Join-Path $repoRoot "tools\trading_listing_event_history_collect_approval_packet.ps1"
$collectorModule = Join-Path $repoRoot "trading_mvp\src\listing_event_history_collector.py"
$requiredApprovalText = "подтверждаю visible listing-event OHLCV history collect"

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

function ConvertTo-ProcessArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)

    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    return '"' + ($Value -replace '"', '\"') + '"'
}

function Write-Gate {
    param([Parameter(Mandatory = $true)]$Gate)
    $Gate | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
}

if (-not $PlanOnly -and -not $ConfirmedListingHistoryCollect) {
    throw "Explicit approval is required. The user must say exactly: $requiredApprovalText, then run with -ConfirmedListingHistoryCollect. Use -PlanOnly to preview."
}

$ApprovalPacketPath = Resolve-RepoPath $ApprovalPacketPath
$gateBeforeApproval = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
$rawGateBeforeApproval = $null
if (Test-Path -LiteralPath $gatePath) {
    $rawGateBeforeApproval = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
}
$gatePreviewPath = if ($rawGateBeforeApproval -and [string]$rawGateBeforeApproval.preview_path) {
    [string]$rawGateBeforeApproval.preview_path
} else {
    [string]$gateBeforeApproval.preview_path
}
$gateNextGoalDecision = if ($rawGateBeforeApproval -and [string]$rawGateBeforeApproval.next_goal_decision) {
    [string]$rawGateBeforeApproval.next_goal_decision
} else {
    [string]$gateBeforeApproval.next_goal_decision
}

$stoppedResumeFromGate = (
    [string]$gateBeforeApproval.status -eq "STOPPED_INCOMPLETE" -and
    $gateNextGoalDecision -eq "LISTING_EVENT_HISTORY_COLLECT_STOPPED_INCOMPLETE" -and
    [string]$gatePreviewPath
)
if ($stoppedResumeFromGate) {
    if (-not $PreviewPath) {
        $PreviewPath = $gatePreviewPath
    }
    $approval = [pscustomobject]@{
        ok = $true
        status = "READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET"
        start_requires_exact_user_input = $requiredApprovalText
        replay_allowed_now = $false
        grid_allowed_now = $false
        live_orders = $false
        api_keys = $false
        preview = [pscustomobject]@{ path = $PreviewPath }
    }
    Write-Host "Reusing listing-event preview from STOPPED_INCOMPLETE gate: $PreviewPath" -ForegroundColor Yellow
} else {
    if (-not (Test-Path -LiteralPath $ApprovalPacketPath)) {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $approvalPacketScript -Json | Out-Null
    }
    if (-not (Test-Path -LiteralPath $ApprovalPacketPath)) {
        throw "Approval packet not found: $ApprovalPacketPath"
    }

    $approval = & pwsh -NoProfile -ExecutionPolicy Bypass -File $approvalPacketScript -OutputPath $ApprovalPacketPath -Json | ConvertFrom-Json
    if (-not [bool]$approval.ok -or [string]$approval.status -ne "READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET") {
        if ((Test-Path -LiteralPath $ApprovalPacketPath)) {
            $approval = Get-Content -Raw -LiteralPath $ApprovalPacketPath | ConvertFrom-Json
            if ([bool]$approval.ok -and [string]$approval.status -eq "READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET") {
                Write-Host "Reusing existing listing-event approval packet: $ApprovalPacketPath" -ForegroundColor Yellow
            } else {
                throw "Approval packet is not ready: ok=$($approval.ok) status=$($approval.status)"
            }
        } else {
            throw "Approval packet is not ready: ok=$($approval.ok) status=$($approval.status)"
        }
    }
}
if ([string]$approval.start_requires_exact_user_input -ne $requiredApprovalText) {
    throw "Approval packet exact phrase mismatch."
}
if ([bool]$approval.replay_allowed_now -or [bool]$approval.grid_allowed_now -or [bool]$approval.live_orders -or [bool]$approval.api_keys) {
    throw "Approval packet unexpectedly allows replay/grid/live/API."
}

if (-not $PreviewPath) {
    $PreviewPath = [string]$approval.preview.path
}
$PreviewPath = Resolve-RepoPath $PreviewPath
if (-not (Test-Path -LiteralPath $PreviewPath)) {
    throw "Preview path not found: $PreviewPath"
}

$preview = Get-Content -Raw -LiteralPath $PreviewPath | ConvertFrom-Json
$runId = [string]$preview.run_id
$runDir = Resolve-RepoPath ([string]$preview.run_dir)
$outputJsonl = Resolve-RepoPath ([string]$preview.expected_outputs.output_jsonl)
$manifestPath = Resolve-RepoPath ([string]$preview.expected_outputs.manifest_path)
$eventPlanPath = Resolve-RepoPath ([string]$preview.expected_outputs.event_plan_path)
$stdoutPath = Resolve-RepoPath ([string]$preview.expected_outputs.stdout_path)
$stderrPath = Resolve-RepoPath ([string]$preview.expected_outputs.stderr_path)

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

$plan = [ordered]@{
    mode = "listing_event_history_collect_visible_plan"
    would_start = $false
    requires_confirmed_listing_history_collect = $true
    confirmed_listing_history_collect = [bool]$ConfirmedListingHistoryCollect
    research_only = $true
    public_data_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    run_id = $runId
    selected_events = [int]$preview.selection.selected_events
    selected_unique_bases = [int]$preview.selection.selected_unique_bases
    selected_exchange_count = [int]$preview.selection.selected_exchange_count
    estimated_total_requests = [int]$preview.request_budget.estimated_total_requests
    estimated_runtime_min = [double]$preview.request_budget.estimated_runtime_min
    preview_path = $PreviewPath
    output_jsonl = $outputJsonl
    manifest_path = $manifestPath
    event_plan_path = $eventPlanPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    command_after_explicit_approval = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ConfirmedListingHistoryCollect"
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
    $sameStoppedListingRun = (
        [string]$gate.run_id -eq $runId -and
        [string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_COLLECT_STOPPED_INCOMPLETE"
    )
    if (-not $sameStoppedListingRun) {
        throw "Active run gate is STOPPED_INCOMPLETE for another run. Resume or explicitly resolve it before starting a new collect."
    }

    $hasPartialOutput = (Test-Path -LiteralPath $outputJsonl) -and ((Get-Item -LiteralPath $outputJsonl).Length -gt 0)
    $hasPartialManifest = Test-Path -LiteralPath $manifestPath
    if ($hasPartialOutput -or $hasPartialManifest) {
        $failedDir = Join-Path $runDir ("failed_" + (Get-Date).ToString("yyyyMMdd_HHmmss"))
        New-Item -ItemType Directory -Force -Path $failedDir | Out-Null
        foreach ($partialPath in @(
            $outputJsonl,
            $manifestPath,
            "$manifestPath.tmp",
            $eventPlanPath,
            $stdoutPath,
            $stderrPath
        )) {
            if (Test-Path -LiteralPath $partialPath) {
                Move-Item -LiteralPath $partialPath -Destination (Join-Path $failedDir (Split-Path $partialPath -Leaf)) -Force
            }
        }
        Write-Host "Archived partial listing-history artifacts before fresh restart: $failedDir" -ForegroundColor Yellow
    }

    Write-Host "Restarting same listing-event history collect run after pre-data STOPPED_INCOMPLETE: $runId" -ForegroundColor Yellow
}
if ([bool]$gate.replay_allowed) {
    throw "Unexpected gate replay_allowed=true before listing-event history collect."
}
if ([string]$gate.next_goal_decision -notin @(
    "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL",
    "LISTING_EVENT_HISTORY_COLLECT_STOPPED_INCOMPLETE"
)) {
    throw "Unexpected gate next_goal_decision=$($gate.next_goal_decision)"
}

New-Item -ItemType Directory -Force -Path $runDir, (Split-Path $stdoutPath), (Split-Path $gatePath) | Out-Null
Set-Location $repoRoot

foreach ($logPath in @($stdoutPath, $stderrPath)) {
    if ((Test-Path -LiteralPath $logPath) -and ((Get-Item -LiteralPath $logPath).Length -gt 0)) {
        $backupPath = "$logPath.previous.$((Get-Date).ToString('yyyyMMdd_HHmmss'))"
        Move-Item -LiteralPath $logPath -Destination $backupPath -Force
    }
}

$activeGate = [ordered]@{
    schema = "active_run_gate_v1"
    project = "trading_mvp"
    run_id = $runId
    status = "RUNNING"
    created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    purpose = "Visible research-only public OHLCV listing-event history collect; no replay/grid/live/API keys."
    blocking_rule = "While status is RUNNING, do not run replay/grid/backtest/paper-forward/new collectors/code edits. Only status/ETA checks are allowed."
    monitor_pid = $PID
    process_ids = @($PID)
    monitor_script = $PSCommandPath
    preview_path = $PreviewPath
    output_path = $outputJsonl
    output_kind = "jsonl"
    manifest_path = $manifestPath
    event_plan_path = $eventPlanPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    selected_events = [int]$preview.selection.selected_events
    selected_unique_bases = [int]$preview.selection.selected_unique_bases
    selected_exchange_count = [int]$preview.selection.selected_exchange_count
    estimated_total_requests = [int]$preview.request_budget.estimated_total_requests
    replay_allowed = $false
    grid_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    status_check_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
    ready_condition = "manifest.final == true AND decision == LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
    next_step_after_ready = "Run guarded listing-event history data-quality, then normalizer; keep replay/grid/live/API/paper-forward blocked until replay_allowed=true."
}
Write-Gate $activeGate

$argsList = @(
    $collectorModule,
    "--preview", $PreviewPath,
    "--output-jsonl", $outputJsonl,
    "--manifest", $manifestPath,
    "--event-plan", $eventPlanPath,
    "--confirmed-approval-text", $requiredApprovalText,
    "--candles-per-request", $CandlesPerRequest,
    "--sleep-sec", $SleepSec,
    "--timeout-sec", $TimeoutSec,
    "--max-retries", $MaxRetries,
    "--progress-every", $ProgressEvery
)
if ($MaxEvents -gt 0) {
    $argsList += @("--max-events", $MaxEvents)
}

Write-Host "Starting visible listing-event OHLCV history collect" -ForegroundColor Cyan
Write-Host "Run id: $runId"
Write-Host "Selected events: $($preview.selection.selected_events), bases: $($preview.selection.selected_unique_bases), exchanges: $($preview.selection.selected_exchange_count)"
Write-Host "Estimated requests: $($preview.request_budget.estimated_total_requests), estimated runtime min: $($preview.request_budget.estimated_runtime_min)"
Write-Host "Output: $outputJsonl"
Write-Host "Manifest: $manifestPath"
Write-Host "Event plan: $eventPlanPath"
Write-Host "Stdout: $stdoutPath"
Write-Host "Stderr: $stderrPath"
Write-Host "Status check: pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"

$argumentLine = ($argsList | ForEach-Object { ConvertTo-ProcessArgument -Value ([string]$_) }) -join " "
$proc = Start-Process -FilePath $python -ArgumentList $argumentLine -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
$activeGate.process_ids = @($PID, $proc.Id)
Write-Gate $activeGate
Write-Host "Collector PID: $($proc.Id)"

while (-not $proc.HasExited) {
    try {
        $lineCount = if (Test-Path -LiteralPath $outputJsonl) { (Get-Content -LiteralPath $outputJsonl | Measure-Object -Line).Lines } else { 0 }
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
            $completed = [int]$manifest.completed_event_granularity_requests
            $total = [int]$manifest.planned_event_granularity_requests
            $pct = if ($total -gt 0) { [Math]::Round(($completed / $total) * 100.0, 2) } else { 0 }
            $lastWrite = if (Test-Path -LiteralPath $outputJsonl) { (Get-Item -LiteralPath $outputJsonl).LastWriteTime } else { $null }
            $age = if ($lastWrite) { [Math]::Round(((Get-Date) - $lastWrite).TotalSeconds, 1) } else { $null }
            Write-Host ("[{0}] PID={1} progress={2}/{3} ({4}%) rows={5} placeholders={6} errors={7} http={8} lines={9} final={10} last_write_age_sec={11}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id, $completed, $total, $pct, $manifest.ohlcv_rows, $manifest.placeholder_rows, $manifest.errors, $manifest.http_requests, $lineCount, $manifest.final, $age)
        } else {
            Write-Host ("[{0}] PID={1} manifest not created yet lines={2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id, $lineCount)
        }
        if ((Test-Path -LiteralPath $stderrPath) -and (Get-Item -LiteralPath $stderrPath).Length -gt 0) {
            Write-Host "--- stderr tail ---" -ForegroundColor Yellow
            Get-Content -LiteralPath $stderrPath -Tail 5
            Write-Host "--- end stderr tail ---" -ForegroundColor Yellow
        }
    } catch {
        Write-Host ("[{0}] monitor error: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message) -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 10
}

$proc.Refresh()
$finalGate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
$finalManifest = $null
if (Test-Path -LiteralPath $manifestPath) {
    $finalManifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
}

$completedOk = ($proc.ExitCode -eq 0 -and $finalManifest -and [bool]$finalManifest.final)
Set-JsonProperty -Object $finalGate -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty -Object $finalGate -Name "status" -Value ($(if ($completedOk) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }))
Set-JsonProperty -Object $finalGate -Name "final" -Value ([bool]$completedOk)
Set-JsonProperty -Object $finalGate -Name "stop_reason" -Value ($(if ($completedOk) { "completed" } else { "collector_exit_$($proc.ExitCode)" }))
Set-JsonProperty -Object $finalGate -Name "monitor_pid_alive" -Value $false
Set-JsonProperty -Object $finalGate -Name "replay_allowed" -Value $false
Set-JsonProperty -Object $finalGate -Name "grid_allowed" -Value $false
Set-JsonProperty -Object $finalGate -Name "paper_forward_allowed" -Value $false
Set-JsonProperty -Object $finalGate -Name "next_goal_decision" -Value ($(if ($completedOk) { "LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY" } else { "LISTING_EVENT_HISTORY_COLLECT_STOPPED_INCOMPLETE" }))
Set-JsonProperty -Object $finalGate -Name "next_goal_reason" -Value ($(if ($completedOk) { "Listing-event OHLCV history collect completed: rows=$($finalManifest.ohlcv_rows), placeholders=$($finalManifest.placeholder_rows), errors=$($finalManifest.errors)." } else { "Listing-event OHLCV history collect did not complete; inspect stdout/stderr/manifest before any replay/grid." }))
Set-JsonProperty -Object $finalGate -Name "next_step_after_ready" -Value "Run guarded listing-event history data-quality, then listing-event normalizer. Do not run replay/grid/live/API/paper-forward until replay_allowed=true."
Set-JsonProperty -Object $finalGate -Name "raw_gate_next_step_after_ready" -Value $finalGate.next_step_after_ready
Set-JsonProperty -Object $finalGate -Name "last_listing_event_history_collect_manifest_path" -Value $manifestPath
Set-JsonProperty -Object $finalGate -Name "last_listing_event_history_collect_output_path" -Value $outputJsonl
Set-JsonProperty -Object $finalGate -Name "last_listing_event_history_collect_event_plan_path" -Value $eventPlanPath
if ($finalManifest) {
    Set-JsonProperty -Object $finalGate -Name "rows" -Value ([int]$finalManifest.ohlcv_rows + [int]$finalManifest.placeholder_rows)
    Set-JsonProperty -Object $finalGate -Name "errors" -Value ([int]$finalManifest.errors)
    Set-JsonProperty -Object $finalGate -Name "expected_outputs_complete" -Value ([bool]$finalManifest.final)
}
Write-Gate $finalGate

Write-Host ""
Write-Host "Listing-event OHLCV history collect finished" -ForegroundColor Cyan
Write-Host "Exit code: $($proc.ExitCode)"
Write-Host "Gate status: $($finalGate.status)"
Write-Host "Decision: $($finalGate.next_goal_decision)"
Write-Host "Manifest: $manifestPath"
Write-Host "Output: $outputJsonl"
if ($finalManifest) {
    Write-Host "Rows: $($finalManifest.ohlcv_rows), placeholders: $($finalManifest.placeholder_rows), errors: $($finalManifest.errors), http: $($finalManifest.http_requests)"
}

if (-not $NoPause) {
    Write-Host ""
    Read-Host "Press Enter to close this visible collector window"
}
