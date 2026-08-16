param(
    [string]$PlanPath = "",
    [string]$ExpectedPlanHash = "",
    [string]$ExpectedPlanFileSha256 = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-first-days-collect-planonly-20260816.json"
if (-not $PlanPath) { $PlanPath = $defaultPlanPath }
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$claimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$collectorPy = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_listing_momentum_first_days_collector.py"
$collectorModule = Join-Path $repoRoot "trading_mvp\src"

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-JsonFile([string]$Path) {
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Write-JsonFile([string]$Path, $Payload) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Invoke-Preflight {
    $reasons = [System.Collections.Generic.List[string]]@()
    if (-not (Test-Path -LiteralPath $PlanPath)) {
        throw "Plan file not found: $PlanPath"
    }
    $plan = Read-JsonFile -Path $PlanPath
    $planFileSha = Get-FileSha256 $PlanPath
    if ($ExpectedPlanFileSha256 -and $planFileSha -ne $ExpectedPlanFileSha256.ToLowerInvariant()) {
        $reasons.Add("plan_file_sha256_mismatch")
    }
    if ($ExpectedPlanHash -and [string]$plan.plan_hash -ne $ExpectedPlanHash.ToLowerInvariant()) {
        $reasons.Add("plan_hash_mismatch")
    }
    $receiptPath = [string]$plan.source_bindings.proxy_acceptance_receipt.path
    if (-not (Test-Path -LiteralPath $receiptPath)) {
        $reasons.Add("proxy_receipt_missing")
    } else {
        $receiptSha = Get-FileSha256 $receiptPath
        if ($receiptSha -ne [string]$plan.source_bindings.proxy_acceptance_receipt.receipt_file_sha256) {
            $reasons.Add("proxy_receipt_sha_mismatch")
        }
    }
    $matPath = [string]$plan.source_bindings.materialization.path
    if (-not (Test-Path -LiteralPath $matPath)) {
        $reasons.Add("materialization_missing")
    } else {
        $mat = Read-JsonFile -Path $matPath
        if ([string]$mat.materialization_hash -ne [string]$plan.source_bindings.materialization.materialization_hash) {
            $reasons.Add("materialization_hash_mismatch")
        }
    }
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ([string]$gate.gate_status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        $reasons.Add("active_run_gate_$($gate.gate_status)")
    }
    if (Test-Path -LiteralPath $claimPath) {
        $reasons.Add("global_writer_claim_exists")
    }
    $outputRoot = [string]$plan.execution.output_root
    if ((Test-Path -LiteralPath (Join-Path $outputRoot "ohlcv.jsonl")) -or
        (Test-Path -LiteralPath (Join-Path $outputRoot "manifest.json"))) {
        $reasons.Add("output_namespace_not_empty")
    }
    return [ordered]@{
        ok = ($reasons.Count -eq 0)
        reasons = $reasons
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = $planFileSha
        job_count = [int]$plan.universe.job_count
        jobs_by_venue = $plan.universe.jobs_by_venue
        max_runtime_sec = [int]$plan.execution.max_runtime_sec
        gate_status = [string]$gate.gate_status
        global_writer_claim_present = (Test-Path -LiteralPath $claimPath)
        output_root = $outputRoot
    }
}

if ($Status) {
    $status = & python $collectorPy --plan $PlanPath --status 2>&1 | Out-String
    $launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\slow_liquidity_listing_momentum_first_days_collect_20260816.launch.json"
    $launch = if (Test-Path -LiteralPath $launchRecordPath) { Read-JsonFile -Path $launchRecordPath } else { $null }
    $payload = [ordered]@{
        collector_status = ($status | ConvertFrom-Json)
        launch_record = $launch
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 12 } else {
        Write-Host "=== listing momentum first-days collect status ===" -ForegroundColor Cyan
        Write-Host $status
        if ($launch) { Write-Host ("launch status: " + $launch.status) }
    }
    exit 0
}

if ($VisibleWorker) {
    $plan = Read-JsonFile -Path $PlanPath
    $outputRoot = [string]$plan.execution.output_root
    $stdoutLog = Join-Path $outputRoot "stdout.log"
    $stderrLog = Join-Path $outputRoot "stderr.log"
    $launchRecordPath = [string]$plan.execution.launch_record_path
    $workerErrorLog = Join-Path $repoRoot ("docs\agent-log\run-gates\" + [string]$plan.execution.run_id + ".worker-error.log")
    if (-not (Test-Path -LiteralPath $outputRoot)) {
        New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
    }
    $pointerPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
    try {
    $startedUtc = (Get-Date).ToUniversalTime().ToString("o")
    $launchRecord = [ordered]@{
        schema = "trading_mvp_listing_momentum_first_days_collect_launch_v1"
        status = "RUNNING"
        run_id = [string]$plan.execution.run_id
        visible_terminal_pid = $PID
        terminal_ownership_verified = $true
        writer_pid = $null
        started_at_utc = $startedUtc
        plan_path = $PlanPath
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = Get-FileSha256 $PlanPath
        proxy_receipt_path = [string]$plan.source_bindings.proxy_acceptance_receipt.path
        proxy_receipt_sha256 = [string]$plan.source_bindings.proxy_acceptance_receipt.receipt_file_sha256
        output_root = $outputRoot
        manifest_path = [string]$plan.execution.manifest_path
        research_only = $true
        public_data_only = $true
    }
    Write-JsonFile -Path $launchRecordPath -Payload $launchRecord
    Write-JsonFile -Path $pointerPath -Payload ([ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = [string]$plan.execution.run_id
        status = "RUNNING"
        updated_at = (Get-Date).ToString("o")
        manifest_path = [string]$plan.execution.manifest_path
        output = @{ path = [string]$plan.execution.output_jsonl; kind = "file" }
        collector_pid = $null
        monitor_pid = $PID
        process_ids = @()
        launch_record_path = $launchRecordPath
    })
    Write-Host "=== listing momentum first-days collect (visible) ===" -ForegroundColor Cyan
    Write-Host "plan_hash: $($plan.plan_hash)"
    Write-Host "jobs: $($plan.universe.job_count)  max_runtime_sec: $($plan.execution.max_runtime_sec)"
    $exitCode = 0
    try {
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        & python $collectorPy --plan $PlanPath --confirmed-visible-collect 1> $stdoutLog 2> $stderrLog
        $exitCode = $LASTEXITCODE
        Get-Content -LiteralPath $stdoutLog -ErrorAction SilentlyContinue | Write-Host
        if (Test-Path -LiteralPath $stderrLog) {
            Get-Content -LiteralPath $stderrLog -ErrorAction SilentlyContinue | Write-Host -ForegroundColor DarkYellow
        }
    } finally {
        $finalStatus = "FAILED"
        $pointerStatus = "STOPPED_INCOMPLETE"
        if ($exitCode -eq 0 -and (Test-Path -LiteralPath ([string]$plan.execution.manifest_path))) {
            $manifest = Read-JsonFile -Path ([string]$plan.execution.manifest_path)
            if ([string]$manifest.status -eq "COMPLETED") {
                $finalStatus = "COMPLETE"
                $pointerStatus = "READY_FOR_POSTPROCESS"
            } elseif ([string]$manifest.status -eq "STOPPED_INCOMPLETE") {
                $finalStatus = "STOPPED_INCOMPLETE"
            }
        }
        $launchRecord.status = $finalStatus
        $launchRecord | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue (Get-Date).ToUniversalTime().ToString("o") -Force
        $launchRecord | Add-Member -NotePropertyName collector_exit_code -NotePropertyValue $exitCode -Force
        Write-JsonFile -Path $launchRecordPath -Payload $launchRecord
        Write-JsonFile -Path $pointerPath -Payload ([ordered]@{
            schema = "active_run_pointer_v1"
            project = "trading_mvp"
            run_id = [string]$plan.execution.run_id
            status = $pointerStatus
            updated_at = (Get-Date).ToString("o")
            manifest_path = [string]$plan.execution.manifest_path
            output = @{ path = [string]$plan.execution.output_jsonl; kind = "file" }
            collector_pid = $null
            monitor_pid = $null
            process_ids = @()
            launch_record_path = $launchRecordPath
        })
        Write-Host "final status: $finalStatus" -ForegroundColor Green
        Start-Sleep -Seconds 5
    }
    } catch {
        ("worker failed at " + (Get-Date).ToUniversalTime().ToString("o") + "`n" +
            ($_ | Out-String) + "`n" +
            ($Error | Select-Object -First 5 | Out-String)) |
            Set-Content -LiteralPath $workerErrorLog -Encoding UTF8
        Write-Host "worker failed; see $workerErrorLog" -ForegroundColor Red
        Start-Sleep -Seconds 10
        exit 1
    }
    exit $exitCode
}

$preflight = Invoke-Preflight
if ($PreflightOnly) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
        Write-Host "=== preflight ===" -ForegroundColor Cyan
        Write-Host ("ok: " + $preflight.ok)
        if ($preflight.reasons.Count -gt 0) { Write-Host ("reasons: " + ($preflight.reasons -join ", ")) }
        Write-Host ("gate: " + $preflight.gate_status + "  jobs: " + $preflight.job_count)
    }
    exit 0
}

if (-not $preflight.ok) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
        Write-Host "preflight failed:" -ForegroundColor Red
        Write-Host ($preflight.reasons -join ", ")
    }
    exit 1
}

$pwshExe = (Get-Process -Id $PID).Path
$childArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
    "-VisibleWorker", "-PlanPath", $PlanPath
)
$terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
$payload = [ordered]@{
    status = "VISIBLE_TERMINAL_LAUNCHED"
    run_id = "slow_liquidity_listing_momentum_first_days_collect_20260816"
    visible_terminal_pid = $terminal.Id
    plan_hash = $preflight.plan_hash
    monitor_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
}
if ($Json) { $payload | ConvertTo-Json -Depth 6 } else {
    Write-Host "visible terminal launched (pid $($terminal.Id))" -ForegroundColor Green
    Write-Host "monitor: pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
}
exit 0
