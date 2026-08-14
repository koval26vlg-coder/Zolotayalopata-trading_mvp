param(
    [string]$PlanPath = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanHash = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanFileSha256 = "",
    [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
    [string]$ExpectedApprovalReceiptSha256 = "",
    [switch]$PreflightOnly,
    [switch]$VisibleWorker,
    [switch]$Status,
    [switch]$Stop,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot `
    "docs\plans\slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
$guardScript = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$policyPath = Join-Path $repoRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$collectorModule = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_history_collector.py"
$controlPlaneModule = Join-Path $repoRoot `
    "trading_mvp\src\slow_liquidity_recollect_control_plane.py"
$writerClaimCli = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"
$globalWriterClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$globalWriterClaimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$collectorApprovalText = "подтверждаю visible slow-liquidity OHLCV history collect"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -DateKind String
}

function ConvertTo-JsonBytes {
    param([Parameter(Mandatory = $true)]$Object)
    $json = $Object | ConvertTo-Json -Depth 30
    return [System.Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Object
    )
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporary = Join-Path $directory (".{0}.{1}.{2}.tmp" -f (
        [System.IO.Path]::GetFileName($Path),
        $PID,
        [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    ))
    try {
        [System.IO.File]::WriteAllBytes($temporary, (ConvertTo-JsonBytes -Object $Object))
        [System.IO.File]::Move($temporary, $Path, $true)
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Write-JsonCreateNew {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Object
    )
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $stream = [System.IO.FileStream]::new(
        $Path,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::Read
    )
    try {
        $bytes = ConvertTo-JsonBytes -Object $Object
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
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

function Assert-ExactHash {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actualText = ([string]$Actual).ToLowerInvariant()
    $expectedText = ([string]$Expected).ToLowerInvariant()
    if (
        $actualText -notmatch '^[0-9a-f]{64}$' -or
        $expectedText -notmatch '^[0-9a-f]{64}$' -or
        $actualText -ne $expectedText
    ) {
        throw "$Label mismatch."
    }
}

function Assert-ExactPath {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actualPath = Get-NormalizedPath -Path ([string]$Actual)
    $expectedPath = Get-NormalizedPath -Path ([string]$Expected)
    if (-not [System.StringComparer]::OrdinalIgnoreCase.Equals($actualPath, $expectedPath)) {
        throw "$Label mismatch."
    }
}

function Assert-ExactStringArray {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actualValues = @($Actual | ForEach-Object { [string]$_ })
    if ($actualValues.Count -ne $Expected.Count) {
        throw "$Label count mismatch."
    }
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        if ($actualValues[$index] -cne $Expected[$index]) {
            throw "$Label mismatch at index $index."
        }
    }
}

function Resolve-ProjectPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Get-NormalizedPath -Path $candidate)
        }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "Python runtime not found."
}

function Test-VisibleConsoleWindow {
    if (-not $IsWindows) { return $false }
    if ($null -eq ("TradingMvp.VisibleConsoleNative" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace TradingMvp {
    public static class VisibleConsoleNative {
        [DllImport("kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWindowVisible(IntPtr hWnd);
    }
}
'@
    }
    $consoleWindow = [TradingMvp.VisibleConsoleNative]::GetConsoleWindow()
    return (
        $consoleWindow -ne [IntPtr]::Zero -and
        [TradingMvp.VisibleConsoleNative]::IsWindowVisible($consoleWindow)
    )
}

function ConvertTo-ProcessArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Join-ProcessArguments {
    param([Parameter(Mandatory = $true)][string[]]$Values)
    return ($Values | ForEach-Object { ConvertTo-ProcessArgument -Value $_ }) -join " "
}

function Get-DirectoryLength {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return [long]0
    }
    $sum = (Get-ChildItem -LiteralPath $Path -File -Recurse -ErrorAction Stop |
        Measure-Object -Property Length -Sum).Sum
    return [long]$(if ($null -eq $sum) { 0 } else { $sum })
}

function Invoke-AutopilotGuard {
    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $guardScript -Json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot guard failed: $(@($raw) -join ' ')"
    }
    return (($raw | Out-String) | ConvertFrom-Json -DateKind String)
}

function Invoke-ControlPlaneValidation {
    param(
        [Parameter(Mandatory = $true)]$PlanBinding,
        [Parameter(Mandatory = $true)]$ReceiptBinding,
        [Parameter(Mandatory = $true)]$Guard
    )
    $policySha256 = Get-Sha256 -Path $policyPath
    if ([string]$Guard.policy_hash -ne $policySha256) {
        return [ordered]@{
            status = "INVALID"
            errors = @("guard_policy_hash_mismatch")
            policy_file_sha256 = $policySha256
        }
    }
    $raw = & $script:python $controlPlaneModule @(
        "validate",
        "--plan", $PlanBinding.path,
        "--expected-plan-file-sha256", $PlanBinding.file_sha256,
        "--expected-plan-hash", $PlanBinding.hash,
        "--receipt", $ReceiptBinding.path,
        "--expected-receipt-file-sha256", $ReceiptBinding.file_sha256,
        "--policy", $policyPath,
        "--gate", $gatePath
    ) 2>&1
    $exitCode = $LASTEXITCODE
    $text = (@($raw) -join [Environment]::NewLine).Trim()
    try {
        $value = $text | ConvertFrom-Json -DateKind String
    } catch {
        return [ordered]@{
            status = "INVALID"
            errors = @("control_plane_validator_invalid_json")
            policy_file_sha256 = $policySha256
        }
    }
    if ($exitCode -ne 0 -or [string]$value.status -ne "VALID") {
        return [ordered]@{
            status = "INVALID"
            errors = @($value.errors)
            policy_file_sha256 = $policySha256
        }
    }
    return [ordered]@{
        status = "VALID"
        errors = @()
        policy_file_sha256 = $policySha256
    }
}

function Get-PlanBinding {
    if ([string]::IsNullOrWhiteSpace($script:PlanPath)) {
        $script:PlanPath = $defaultPlanPath
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedPlanHash)) {
        throw "ExpectedPlanHash is required."
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedPlanFileSha256)) {
        throw "ExpectedPlanFileSha256 is required."
    }
    $resolvedPlanPath = Get-NormalizedPath -Path $script:PlanPath
    if (-not (Test-Path -LiteralPath $resolvedPlanPath -PathType Leaf)) {
        throw "Plan is missing: $resolvedPlanPath"
    }
    Assert-ExactHash (Get-Sha256 -Path $resolvedPlanPath) $ExpectedPlanFileSha256 `
        "plan.file_sha256"
    $plan = Read-JsonFile -Path $resolvedPlanPath
    if ([string]$plan.schema -ne "trading_mvp_slow_liquidity_history_recollect_planonly_v1") {
        throw "Plan schema mismatch."
    }
    if ([string]$plan.status -ne "AWAIT_EXACT_HASH_BOUND_APPROVAL") {
        throw "Plan status mismatch."
    }
    if ([bool]$plan.actual_collection_allowed) {
        throw "Plan must remain PlanOnly before the separate receipt."
    }
    Assert-ExactHash $plan.plan_hash $ExpectedPlanHash "plan.plan_hash"
    if (
        [string]$plan.plan_id -cne "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6" -or
        [string]$plan.strategy_branch -cne "slow_liquidity_regime_breakout_retest" -or
        [string]$plan.execution.run_id -cne "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6" -or
        [int]$plan.execution.history_days -ne 56 -or
        [int]$plan.execution.target_bases -ne 9 -or
        [int]$plan.execution.candles_per_request -ne 1000 -or
        [int]$plan.execution.max_retries -ne 1 -or
        [int]$plan.execution.logical_requests -ne 63 -or
        [int]$plan.execution.maximum_http_attempts -ne 126 -or
        [int]$plan.execution.max_runtime_sec -ne 900 -or
        [long]$plan.execution.hard_output_cap_bytes -ne 100000000 -or
        [bool]$plan.execution.resume_allowed -or
        [bool]$plan.execution.stopped_incomplete_retry_authorized -or
        -not [bool]$plan.execution.visible_terminal_required -or
        -not [bool]$plan.execution.single_global_writer_required
    ) {
        throw "Plan frozen execution contract mismatch."
    }
    Assert-ExactStringArray $plan.universe.bases @(
        "STETH", "WEETH", "CC", "OKB", "RAIN", "MNT", "USDD", "BDX", "EDGE"
    ) "plan.universe.bases"
    Assert-ExactStringArray $plan.execution.exchanges @("mexc", "gateio") `
        "plan.execution.exchanges"
    Assert-ExactStringArray $plan.execution.timeframes @("1h", "4h") `
        "plan.execution.timeframes"
    Assert-ExactPath $plan.launcher.path $PSCommandPath "plan.launcher.path"
    Assert-ExactHash $plan.launcher.sha256 (Get-Sha256 -Path $PSCommandPath) `
        "plan.launcher.sha256"

    foreach ($binding in @($plan.implementation.files)) {
        $path = Get-NormalizedPath -Path ([string]$binding.path)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Bound implementation file is missing: $path"
        }
        Assert-ExactHash (Get-Sha256 -Path $path) $binding.sha256 `
            "implementation.$([string]$binding.role).sha256"
    }
    $universePath = Get-NormalizedPath -Path ([string]$plan.universe.path)
    if (-not (Test-Path -LiteralPath $universePath -PathType Leaf)) {
        throw "Frozen universe is missing: $universePath"
    }
    Assert-ExactHash (Get-Sha256 -Path $universePath) $plan.universe.sha256 `
        "universe.sha256"

    return [ordered]@{
        path = $resolvedPlanPath
        file_sha256 = $ExpectedPlanFileSha256.ToLowerInvariant()
        hash = $ExpectedPlanHash.ToLowerInvariant()
        value = $plan
    }
}

function Get-ReceiptBinding {
    param(
        [Parameter(Mandatory = $true)]$PlanBinding,
        [switch]$AllowMissing
    )
    $plan = $PlanBinding.value
    $receiptPath = Get-NormalizedPath -Path ([string]$plan.approval_receipt.path)
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        if ($AllowMissing) {
            return $null
        }
        throw "Exact approval receipt is missing: $receiptPath"
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedApprovalReceiptSha256)) {
        if ($AllowMissing) {
            return $null
        }
        throw "ExpectedApprovalReceiptSha256 is required after approval."
    }
    Assert-ExactHash (Get-Sha256 -Path $receiptPath) `
        $ExpectedApprovalReceiptSha256 "receipt.file_sha256"
    $receipt = Read-JsonFile -Path $receiptPath
    if (
        [string]$receipt.schema -ne "trading_mvp_slow_liquidity_history_recollect_approval_v1" -or
        [string]$receipt.status -ne "APPROVED" -or
        [string]$receipt.approval_type -ne "EXACT_HASH_BOUND_VISIBLE_PUBLIC_RECOLLECT" -or
        -not [bool]$receipt.single_use -or
        [bool]$receipt.stop_incomplete_retry_authorized
    ) {
        throw "Exact approval receipt contract mismatch."
    }
    Assert-ExactPath $receipt.plan_path $PlanBinding.path "receipt.plan_path"
    Assert-ExactHash $receipt.plan_file_sha256 $PlanBinding.file_sha256 `
        "receipt.plan_file_sha256"
    Assert-ExactHash $receipt.plan_hash $PlanBinding.hash "receipt.plan_hash"
    if ([string]$receipt.run_id -cne [string]$plan.execution.run_id) {
        throw "receipt.run_id mismatch."
    }
    if (
        [long]$receipt.max_runtime_sec -ne [long]$plan.execution.max_runtime_sec -or
        [long]$receipt.hard_output_cap_bytes -ne [long]$plan.execution.hard_output_cap_bytes -or
        [long]$receipt.maximum_http_attempts -ne [long]$plan.execution.maximum_http_attempts
    ) {
        throw "Receipt resource limits mismatch."
    }
    Assert-ExactStringArray $receipt.bases @($plan.universe.bases) "receipt.bases"
    Assert-ExactStringArray $receipt.exchanges @($plan.execution.exchanges) `
        "receipt.exchanges"
    Assert-ExactStringArray $receipt.timeframes @($plan.execution.timeframes) `
        "receipt.timeframes"
    if (
        [string]$receipt.policy_rebind_status -ne
            "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL" -or
        [string]$receipt.required_guard_decision -ne
            [string]$plan.guard_contract.required_decision_after_approval
    ) {
        throw "Receipt guard rebind mismatch."
    }
    return [ordered]@{
        path = $receiptPath
        file_sha256 = $ExpectedApprovalReceiptSha256.ToLowerInvariant()
        value = $receipt
    }
}

function Invoke-FullPreflight {
    param([switch]$IgnoreOwnLaunchRecord)
    $planBinding = Get-PlanBinding
    $plan = $planBinding.value
    $receiptBinding = Get-ReceiptBinding -PlanBinding $planBinding -AllowMissing
    $guard = Invoke-AutopilotGuard
    $reasons = [System.Collections.Generic.List[string]]::new()
    $controlPlaneValidation = $null

    if ([string]$guard.status -ne "ACTIVE") { $reasons.Add("guard_not_active") }
    if ([bool]$guard.stop_new_actions) { $reasons.Add("guard_stops_new_actions") }
    if ([string]$guard.usage.status -ne "AVAILABLE") { $reasons.Add("usage_unavailable") }
    if ([double]$guard.usage.remaining_percent -le 15.0) { $reasons.Add("weekly_limit") }
    if ([string]$guard.usage.decision -ne "CONTINUE") { $reasons.Add("usage_guard_blocked") }
    if ([string]$guard.gate.status -eq "RUNNING") { $reasons.Add("active_gate_running") }
    if ([string]$guard.gate.status -eq "STOPPED_INCOMPLETE") {
        $reasons.Add("active_gate_stopped_incomplete")
    }
    if (-not $receiptBinding) {
        $reasons.Add("exact_approval_receipt_missing")
    } else {
        $controlPlaneValidation = Invoke-ControlPlaneValidation `
            -PlanBinding $planBinding -ReceiptBinding $receiptBinding -Guard $guard
        if ([string]$controlPlaneValidation.status -ne "VALID") {
            $reasons.Add("policy_rebind_missing_or_invalid")
        }
        if (
            [string]$guard.gate.next_goal_decision -ne
            [string]$plan.guard_contract.required_decision_after_approval
        ) {
            $reasons.Add("guard_not_exactly_rebound")
        }
    }

    $launchRecordPath = Get-NormalizedPath -Path ([string]$plan.execution.launch_record_path)
    $outputPath = Get-NormalizedPath -Path ([string]$plan.execution.output_path)
    if ((Test-Path -LiteralPath $launchRecordPath) -and -not $IgnoreOwnLaunchRecord) {
        $reasons.Add("single_use_launch_record_exists")
    }
    if (Test-Path -LiteralPath $outputPath) {
        $reasons.Add("immutable_output_namespace_exists")
    }
    if (Test-Path -LiteralPath $globalWriterClaimPath) {
        $reasons.Add("global_writer_claim_exists")
    }
    $outputDriveRoot = [System.IO.Path]::GetPathRoot($outputPath)
    try {
        $outputDrive = [System.IO.DriveInfo]::new($outputDriveRoot)
        if ([long]$outputDrive.AvailableFreeSpace -lt [long]$plan.execution.min_free_disk_bytes) {
            $reasons.Add("insufficient_free_disk")
        }
    } catch {
        $reasons.Add("output_drive_unavailable")
    }

    $now = [DateTimeOffset]::Now
    $notBefore = [DateTimeOffset]::Parse([string]$plan.execution.not_before_local)
    $latestStart = [DateTimeOffset]::Parse([string]$plan.execution.latest_start_local)
    $hardDeadline = [DateTimeOffset]::Parse([string]$plan.execution.hard_deadline_local)
    if ($now -lt $notBefore) { $reasons.Add("launch_window_not_open") }
    if ($now -gt $latestStart) { $reasons.Add("latest_start_passed") }
    if ($now.AddSeconds([int]$plan.execution.max_runtime_sec) -gt $hardDeadline) {
        $reasons.Add("full_runtime_exceeds_hard_deadline")
    }

    $status = if (-not $receiptBinding) {
        "BLOCKED_AWAITING_EXACT_APPROVAL"
    } elseif ($reasons.Count -eq 0) {
        "READY_FOR_VISIBLE_SINGLE_USE"
    } else {
        "BLOCKED"
    }
    return [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_preflight_v1"
        status = $status
        would_start = $false
        run_id = [string]$plan.execution.run_id
        reasons = @($reasons)
        plan_path = $planBinding.path
        plan_file_sha256 = $planBinding.file_sha256
        plan_hash = $planBinding.hash
        approval_receipt_path = Get-NormalizedPath -Path ([string]$plan.approval_receipt.path)
        approval_receipt_present = [bool]$receiptBinding
        guard_status = [string]$guard.status
        gate_status = [string]$guard.gate.status
        gate_next_goal_decision = [string]$guard.gate.next_goal_decision
        guard_policy_hash = [string]$guard.policy_hash
        control_plane_validation = $controlPlaneValidation
        weekly_remaining_percent = [double]$guard.usage.remaining_percent
        usage_event_age_sec = [double]$guard.usage.event_age_sec
        global_writer_claim_present = Test-Path -LiteralPath $globalWriterClaimPath
        launch_record_present = Test-Path -LiteralPath $launchRecordPath
        output_present = Test-Path -LiteralPath $outputPath
        output_path = $outputPath
        max_runtime_sec = [int]$plan.execution.max_runtime_sec
        hard_output_cap_bytes = [long]$plan.execution.hard_output_cap_bytes
        logical_requests = [int]$plan.execution.logical_requests
        maximum_http_attempts = [int]$plan.execution.maximum_http_attempts
        network_accessed = $false
        output_created = $false
    }
}

function Invoke-ClaimCommand {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $raw = & $script:python $writerClaimCli @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Global writer claim command failed: $(@($raw) -join ' ')"
    }
    return (($raw | Out-String) | ConvertFrom-Json -DateKind String)
}

function Set-LaunchRecord {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $Record.status = $State
    $Record.message = $Message
    $Record.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    Write-JsonAtomic -Path $Path -Object $Record
}

function Set-ActiveGateForRun {
    param(
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$Decision,
        [Parameter(Mandatory = $true)][string]$Reason,
        [int]$WriterPid = 0,
        [string]$ManifestPath = "",
        [string]$OutputPath = ""
    )
    $gate = if (Test-Path -LiteralPath $gatePath -PathType Leaf) {
        Read-JsonFile -Path $gatePath
    } else {
        [pscustomobject]@{ schema = "active_run_gate_v1"; project = "trading_mvp" }
    }
    Set-JsonProperty $gate "run_id" ([string]$Plan.execution.run_id)
    $terminalState = $State -ne "RUNNING"
    Set-JsonProperty $gate "status" $State
    Set-JsonProperty $gate "updated_at" ([DateTimeOffset]::Now.ToString("o"))
    Set-JsonProperty $gate "final" ($State -eq "READY_FOR_POSTPROCESS")
    Set-JsonProperty $gate "purpose" "Exact public read-only MEXC/Gate 1h/4h page-cap correction recollect."
    Set-JsonProperty $gate "next_goal_decision" $Decision
    Set-JsonProperty $gate "next_goal_reason" $Reason
    Set-JsonProperty $gate "next_step_after_ready" `
        "Run only the frozen recollect data-quality gate; evaluator/OOS/PnL/grid/retune/paper/live remain blocked."
    Set-JsonProperty $gate "replay_allowed" $false
    Set-JsonProperty $gate "grid_allowed" $false
    Set-JsonProperty $gate "paper_forward_allowed" $false
    Set-JsonProperty $gate "live_orders" $false
    Set-JsonProperty $gate "api_keys" $false
    Set-JsonProperty $gate "leverage_or_margin" $false
    Set-JsonProperty $gate "resume_command" ""
    Set-JsonProperty $gate "stopped_incomplete_retry_authorized" $false
    $processIds = @()
    if (-not $terminalState) {
        $processIds += $PID
    }
    if (-not $terminalState -and $WriterPid -gt 0) {
        $processIds += $WriterPid
    }
    Set-JsonProperty $gate "process_ids" $processIds
    Set-JsonProperty $gate "monitor_pid" $(if ($terminalState) { $null } else { $PID })
    Set-JsonProperty $gate "collector_pid" $(if (-not $terminalState -and $WriterPid -gt 0) { $WriterPid } else { $null })
    Set-JsonProperty $gate "global_market_writer_claim_path" $globalWriterClaimPath
    Set-JsonProperty $gate "plan_path" (Get-NormalizedPath -Path $PlanPath)
    Set-JsonProperty $gate "plan_hash" ([string]$Plan.plan_hash)
    Set-JsonProperty $gate "output_path" $OutputPath
    Set-JsonProperty $gate "manifest_path" $ManifestPath
    Set-JsonProperty $gate "status_check_command" ([string]$Plan.commands.status)
    Set-JsonProperty $gate "stop_command" ([string]$Plan.commands.stop)
    Write-JsonAtomic -Path $gatePath -Object $gate
    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = [string]$Plan.execution.run_id
        status = $State
        updated_at = [DateTimeOffset]::Now.ToString("o")
        manifest_path = $ManifestPath
        output = [ordered]@{ path = $OutputPath; kind = "file" }
        collector_pid = if ($terminalState -or $WriterPid -le 0) { $null } else { $WriterPid }
        monitor_pid = if ($terminalState) { $null } else { $PID }
        process_ids = $processIds
        launch_record_path = Get-NormalizedPath -Path `
            ([string]$Plan.execution.launch_record_path)
    }
    Write-JsonAtomic -Path $currentRunPath -Object $pointer
}

$modeCount = @($PreflightOnly, $VisibleWorker, $Status, $Stop | Where-Object { $_ }).Count
if ($modeCount -gt 1) {
    throw "PreflightOnly, VisibleWorker, Status, and Stop are mutually exclusive."
}

$python = Resolve-ProjectPython

if ($Status) {
    $binding = Get-PlanBinding
    $recordPath = Get-NormalizedPath -Path ([string]$binding.value.execution.launch_record_path)
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_status_v1"
        run_id = [string]$binding.value.execution.run_id
        launch_record = if (Test-Path -LiteralPath $recordPath) { Read-JsonFile $recordPath } else { $null }
        active_gate = if (Test-Path -LiteralPath $gatePath) { Read-JsonFile $gatePath } else { $null }
        global_writer_claim = if (Test-Path -LiteralPath $globalWriterClaimPath) {
            Read-JsonFile $globalWriterClaimPath
        } else { $null }
    } | ConvertTo-Json -Depth 30
    exit 0
}

if ($Stop) {
    $binding = Get-PlanBinding
    $null = Get-ReceiptBinding -PlanBinding $binding
    $recordPath = Get-NormalizedPath -Path ([string]$binding.value.execution.launch_record_path)
    if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) {
        throw "Exact launch record is missing; there is no owned writer to stop."
    }
    $record = Read-JsonFile -Path $recordPath
    if ([string]$record.run_id -ne [string]$binding.value.execution.run_id) {
        throw "Launch record run_id mismatch."
    }
    if ([string]$record.status -ne "RUNNING") {
        [ordered]@{ status = "NOT_RUNNING"; run_id = [string]$record.run_id; writer_pid = $record.writer_pid } |
            ConvertTo-Json -Depth 5
        exit 0
    }
    if (-not (Test-Path -LiteralPath $globalWriterClaimPath -PathType Leaf)) {
        throw "Global writer claim is missing; refusing to trust a stale PID."
    }
    $claim = Read-JsonFile -Path $globalWriterClaimPath
    $writerPid = [int]$record.writer_pid
    if (
        [string]$claim.run_id -ne [string]$record.run_id -or
        [int]$claim.writer_pid -ne $writerPid -or
        [int]$claim.owner_pid -ne [int]$record.visible_terminal_pid
    ) {
        throw "Global writer claim does not match the exact launch record."
    }
    if (-not (Get-Process -Id ([int]$claim.owner_pid) -ErrorAction SilentlyContinue)) {
        throw "Visible owner is not alive; refusing automatic PID-based stop."
    }
    $process = Get-Process -Id $writerPid -ErrorAction SilentlyContinue
    if (-not $process) {
        [ordered]@{ status = "NOT_RUNNING"; run_id = [string]$record.run_id; writer_pid = $writerPid } |
            ConvertTo-Json -Depth 5
        exit 0
    }
    Stop-Process -Id $writerPid -Force
    [ordered]@{ status = "STOP_REQUESTED"; run_id = [string]$record.run_id; writer_pid = $writerPid } |
        ConvertTo-Json -Depth 5
    exit 0
}

if ($PreflightOnly) {
    Invoke-FullPreflight | ConvertTo-Json -Depth 30
    exit 0
}

if (-not $VisibleWorker) {
    $preflight = Invoke-FullPreflight
    if ([string]$preflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE") {
        throw "Exact recollect is not authorized: $($preflight.status); reasons=$($preflight.reasons -join ',')."
    }
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $childArguments = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath,
        "-PlanPath", $preflight.plan_path,
        "-ExpectedPlanHash", $preflight.plan_hash,
        "-ExpectedPlanFileSha256", $preflight.plan_file_sha256,
        "-ExpectedApprovalReceiptSha256", $ExpectedApprovalReceiptSha256,
        "-VisibleWorker"
    )
    $terminal = Start-Process -FilePath $pwsh -ArgumentList $childArguments `
        -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru

    $binding = Get-PlanBinding
    $recordPath = Get-NormalizedPath -Path ([string]$binding.value.execution.launch_record_path)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    $owned = $null
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if ($terminal.HasExited) {
            throw "Visible recollect terminal exited before claiming the exact run."
        }
        if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
            try {
                $candidate = Read-JsonFile -Path $recordPath
                if (
                    [string]$candidate.run_id -eq [string]$binding.value.execution.run_id -and
                    [int]$candidate.visible_terminal_pid -eq $terminal.Id
                ) {
                    $owned = $candidate
                    break
                }
            } catch {
                # The visible worker may be between exclusive create and atomic update.
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $owned) {
        throw "Visible recollect terminal did not claim the exact run within 30 seconds."
    }
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_visible_launch_v1"
        status = "VISIBLE_TERMINAL_LAUNCHED"
        run_id = [string]$binding.value.execution.run_id
        visible_terminal_pid = $terminal.Id
        terminal_ownership_verified = $true
        child_status = [string]$owned.status
        launch_record_path = $recordPath
        output_path = [string]$binding.value.execution.output_path
        manifest_path = [string]$binding.value.execution.manifest_path
        max_runtime_sec = [int]$binding.value.execution.max_runtime_sec
        hard_output_cap_bytes = [long]$binding.value.execution.hard_output_cap_bytes
        status_command = [string]$binding.value.commands.status
        stop_command = [string]$binding.value.commands.stop
    } | ConvertTo-Json -Depth 10
    exit 0
}

if (-not (Test-VisibleConsoleWindow)) {
    throw "visible_console_not_verified"
}

$planBinding = Get-PlanBinding
$receiptBinding = Get-ReceiptBinding -PlanBinding $planBinding
$plan = $planBinding.value
$runId = [string]$plan.execution.run_id
$runDir = Get-NormalizedPath -Path ([string]$plan.execution.output_path)
$outputJsonl = Get-NormalizedPath -Path ([string]$plan.execution.output_jsonl)
$manifestPath = Get-NormalizedPath -Path ([string]$plan.execution.manifest_path)
$stdoutPath = Get-NormalizedPath -Path ([string]$plan.execution.stdout_path)
$stderrPath = Get-NormalizedPath -Path ([string]$plan.execution.stderr_path)
$launchRecordPath = Get-NormalizedPath -Path ([string]$plan.execution.launch_record_path)
$universePath = Get-NormalizedPath -Path ([string]$plan.universe.path)
$maxRuntimeSec = [int]$plan.execution.max_runtime_sec
$hardOutputCapBytes = [long]$plan.execution.hard_output_cap_bytes
$hardDeadline = [DateTimeOffset]::Parse([string]$plan.execution.hard_deadline_local)

$launchRecord = [ordered]@{
    schema = "trading_mvp_slow_liquidity_recollect_launch_v1"
    status = "VISIBLE_WORKER_CLAIMED"
    run_id = $runId
    visible_terminal_pid = $PID
    terminal_ownership_verified = $true
    writer_pid = $null
    started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    finished_at_utc = $null
    plan_path = $planBinding.path
    plan_file_sha256 = $planBinding.file_sha256
    plan_hash = $planBinding.hash
    approval_receipt_path = $receiptBinding.path
    approval_receipt_sha256 = $receiptBinding.file_sha256
    output_path = $runDir
    output_jsonl = $outputJsonl
    manifest_path = $manifestPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    max_runtime_sec = $maxRuntimeSec
    hard_output_cap_bytes = $hardOutputCapBytes
    global_writer_claim_path = $globalWriterClaimPath
    global_writer_claim_archive_path = $null
    message = "Visible worker claimed the exact single-use recollect."
    retry_authorized = $false
}

$claimToken = $null
$claimReleased = $false
$writerProcess = $null
$recordOwned = $false

try {
    Write-JsonCreateNew -Path $launchRecordPath -Object $launchRecord
    $recordOwned = $true
    Write-Host "[slow-liquidity-recollect] exact visible worker claimed: $runId" -ForegroundColor Cyan

    $workerPreflight = Invoke-FullPreflight -IgnoreOwnLaunchRecord
    if ([string]$workerPreflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE") {
        throw "Worker preflight blocked execution: $($workerPreflight.reasons -join ',')."
    }
    Set-LaunchRecord $launchRecord $launchRecordPath "PREFLIGHT_PASSED" `
        "Fresh guard, exact hashes, receipt, window, and single-writer state passed."

    $claim = Invoke-ClaimCommand -Arguments @(
        "claim", "--path", $globalWriterClaimPath,
        "--run-id", $runId,
        "--owner-pid", [string]$PID,
        "--owner-kind", "slow_liquidity_history_recollect",
        "--plan-hash", $planBinding.hash,
        "--output-namespace", $runDir,
        "--terminal-pid", [string]$PID
    )
    $claimToken = [string]$claim.ownership_token
    Set-LaunchRecord $launchRecord $launchRecordPath "GLOBAL_WRITER_CLAIMED" `
        "Atomic global market-data writer claim acquired."

    New-Item -ItemType Directory -Path $runDir | Out-Null
    $collectorArguments = @(
        $collectorModule,
        "--run-id", $runId,
        "--universe", $universePath,
        "--output-jsonl", $outputJsonl,
        "--manifest", $manifestPath,
        "--confirmed-approval-text", $collectorApprovalText,
        "--exchanges", (@($plan.execution.exchanges) -join ","),
        "--granularities", (@($plan.execution.timeframes) -join ","),
        "--history-days", [string]$plan.execution.history_days,
        "--target-bases", [string]$plan.execution.target_bases,
        "--candles-per-request", [string]$plan.execution.candles_per_request,
        "--sleep-sec", [string]$plan.execution.sleep_sec,
        "--timeout-sec", [string]$plan.execution.timeout_sec,
        "--max-retries", [string]$plan.execution.max_retries,
        "--progress-every", [string]$plan.execution.progress_every
    )
    $argumentLine = Join-ProcessArguments -Values $collectorArguments
    $writerProcess = Start-Process -FilePath $python -ArgumentList $argumentLine `
        -WorkingDirectory $repoRoot -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath -NoNewWindow -PassThru
    $null = Invoke-ClaimCommand -Arguments @(
        "attach", "--path", $globalWriterClaimPath,
        "--run-id", $runId,
        "--owner-pid", [string]$PID,
        "--ownership-token", $claimToken,
        "--writer-pid", [string]$writerProcess.Id
    )
    $launchRecord.writer_pid = $writerProcess.Id
    Set-LaunchRecord $launchRecord $launchRecordPath "RUNNING" `
        "Public read-only MEXC/Gate OHLCV recollect is running."
    Set-ActiveGateForRun $plan "RUNNING" "SLOW_LIQUIDITY_HISTORY_RECOLLECT_RUNNING" `
        "Exact page-cap correction recollect is running in one visible terminal." `
        -WriterPid $writerProcess.Id -ManifestPath $manifestPath -OutputPath $outputJsonl
    Write-Host "[slow-liquidity-recollect] RUNNING pid=$($writerProcess.Id) max=${maxRuntimeSec}s" -ForegroundColor Green
    Write-Host "[slow-liquidity-recollect] status: $($plan.commands.status)"
    Write-Host "[slow-liquidity-recollect] stop:   $($plan.commands.stop)"

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $writerProcess.HasExited) {
        $size = Get-DirectoryLength -Path $runDir
        if ($size -gt $hardOutputCapBytes) {
            Stop-Process -Id $writerProcess.Id -Force -ErrorAction SilentlyContinue
            throw "Hard output cap exceeded: $size > $hardOutputCapBytes bytes."
        }
        if ($stopwatch.Elapsed.TotalSeconds -ge $maxRuntimeSec) {
            Stop-Process -Id $writerProcess.Id -Force -ErrorAction SilentlyContinue
            throw "Exact recollect exceeded MaxRuntimeSec=$maxRuntimeSec."
        }
        if ([DateTimeOffset]::Now -ge $hardDeadline) {
            Stop-Process -Id $writerProcess.Id -Force -ErrorAction SilentlyContinue
            throw "Exact recollect reached its hard deadline."
        }
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            try {
                $progress = Read-JsonFile -Path $manifestPath
                Write-Host ("[slow-liquidity-recollect] elapsed={0:n1}s jobs={1}/{2} rows={3} errors={4} logical_http={5} bytes={6}" -f @(
                    $stopwatch.Elapsed.TotalSeconds,
                    [int]$progress.completed_market_granularity_requests,
                    [int]$progress.planned_market_granularity_requests,
                    [long]$progress.rows,
                    [long]$progress.errors,
                    [long]$progress.http_requests,
                    $size
                ))
            } catch {
                Write-Host "[slow-liquidity-recollect] manifest update in progress" -ForegroundColor Yellow
            }
        } else {
            Write-Host ("[slow-liquidity-recollect] elapsed={0:n1}s waiting for manifest" -f $stopwatch.Elapsed.TotalSeconds)
        }
        Start-Sleep -Seconds 2
        $writerProcess.Refresh()
    }
    $stopwatch.Stop()
    if ($writerProcess.ExitCode -ne 0) {
        throw "Collector exited with code $($writerProcess.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Collector returned without a manifest."
    }
    $manifest = Read-JsonFile -Path $manifestPath
    if (
        -not [bool]$manifest.final -or
        [string]$manifest.decision -ne "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY" -or
        [string]$manifest.run_id -ne $runId -or
        [int]$manifest.history_days -ne [int]$plan.execution.history_days -or
        [int]$manifest.candles_per_request -ne [int]$plan.execution.candles_per_request -or
        [int]$manifest.planned_market_granularity_requests -ne 36 -or
        [int]$manifest.completed_market_granularity_requests -ne 36 -or
        [int]$manifest.http_requests -gt [int]$plan.execution.logical_requests
    ) {
        throw "Collector manifest is not an exact complete result."
    }
    Assert-ExactStringArray $manifest.selected_bases @($plan.universe.bases) `
        "manifest.selected_bases"
    Assert-ExactStringArray $manifest.exchanges @($plan.execution.exchanges) `
        "manifest.exchanges"
    Assert-ExactStringArray $manifest.granularities @($plan.execution.timeframes) `
        "manifest.granularities"
    $finalBytes = Get-DirectoryLength -Path $runDir
    if ($finalBytes -gt $hardOutputCapBytes) {
        throw "Completed output exceeds the exact cap."
    }

    $released = Invoke-ClaimCommand -Arguments @(
        "release", "--path", $globalWriterClaimPath,
        "--run-id", $runId,
        "--owner-pid", [string]$PID,
        "--ownership-token", $claimToken,
        "--final-status", "READY_FOR_POSTPROCESS",
        "--archive-dir", $globalWriterClaimArchiveDir
    )
    $claimReleased = $true
    $claimToken = $null
    $launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
    $launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    $launchRecord.manifest_sha256 = Get-Sha256 -Path $manifestPath
    $launchRecord.output_jsonl_sha256 = Get-Sha256 -Path $outputJsonl
    $launchRecord.final_bytes = $finalBytes
    Set-LaunchRecord $launchRecord $launchRecordPath "COMPLETE" `
        "Exact recollect completed; only the frozen data-quality gate is next."
    Set-ActiveGateForRun $plan "READY_FOR_POSTPROCESS" `
        "SLOW_LIQUIDITY_HISTORY_RECOLLECT_COMPLETED_READY_FOR_DATA_QUALITY" `
        "Exact page-cap correction recollect completed; run only frozen data quality." `
        -ManifestPath $manifestPath -OutputPath $outputJsonl
    Write-Host "[slow-liquidity-recollect] COMPLETE" -ForegroundColor Green
    Write-Host "[slow-liquidity-recollect] manifest=$manifestPath"
    Write-Host "[slow-liquidity-recollect] output=$outputJsonl"
} catch {
    $failure = $_.Exception.Message
    if ($writerProcess -and -not $writerProcess.HasExited) {
        Stop-Process -Id $writerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($claimToken -and -not $claimReleased) {
        try {
            $released = Invoke-ClaimCommand -Arguments @(
                "release", "--path", $globalWriterClaimPath,
                "--run-id", $runId,
                "--owner-pid", [string]$PID,
                "--ownership-token", $claimToken,
                "--final-status", "STOPPED_INCOMPLETE",
                "--archive-dir", $globalWriterClaimArchiveDir
            )
            $claimReleased = $true
            $claimToken = $null
            $launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
        } catch {
            $failure += " Global writer claim release failed: $($_.Exception.Message)"
        }
    }
    if ($recordOwned) {
        $launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        Set-LaunchRecord $launchRecord $launchRecordPath "STOPPED_INCOMPLETE" $failure
        try {
            Set-ActiveGateForRun $plan "STOPPED_INCOMPLETE" `
                "SLOW_LIQUIDITY_HISTORY_RECOLLECT_STOPPED_INCOMPLETE_NO_RETRY" `
                "$failure No retry is authorized." -ManifestPath $manifestPath `
                -OutputPath $outputJsonl
        } catch {
            $failure += " Active gate update failed: $($_.Exception.Message)"
        }
    }
    Write-Host "[slow-liquidity-recollect] STOPPED_INCOMPLETE: $failure" -ForegroundColor Red
    throw
}
