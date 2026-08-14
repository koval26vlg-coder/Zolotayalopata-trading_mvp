param(
    [string]$PlanPath = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanHash = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanFileSha256 = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedApprovalReceiptSha256 = "",
    [switch]$PreflightOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot `
    "docs\plans\slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
$policyPath = Join-Path $repoRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$currentRunPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
$globalWriterClaimPath = Join-Path $repoRoot `
    "docs\agent-log\active-market-data-writer-claim.json"
$guardScript = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$controlPlaneModule = Join-Path $repoRoot `
    "trading_mvp\src\slow_liquidity_recollect_control_plane.py"
$qualityWrapper = Join-Path $repoRoot `
    "tools\trading_slow_liquidity_history_data_quality.ps1"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-ExactHash {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Actual.ToLowerInvariant() -cne $Expected.ToLowerInvariant()) {
        throw "$Label mismatch."
    }
}

function Assert-ExactPath {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ((Get-NormalizedPath $Actual) -ine (Get-NormalizedPath $Expected)) {
        throw "$Label mismatch."
    }
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 |
        ConvertFrom-Json -Depth 100 -DateKind String)
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

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Object
    )
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    $temporary = Join-Path $directory (".{0}.{1}.tmp" -f `
        [System.IO.Path]::GetFileName($Path), [Guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText(
            $temporary,
            (($Object | ConvertTo-Json -Depth 30) + "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-BytesAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )
    $directory = Split-Path -Parent $Path
    $temporary = Join-Path $directory (".{0}.{1}.tmp" -f `
        [System.IO.Path]::GetFileName($Path), [Guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllBytes($temporary, $Bytes)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
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
    $resolved = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if ($resolved) { return $resolved }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python runtime not found."
}

function Invoke-Guard {
    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $guardScript -Json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot guard failed: $(@($raw) -join ' ')"
    }
    return (($raw | Out-String) | ConvertFrom-Json -Depth 100 -DateKind String)
}

function Get-Context {
    if ([string]::IsNullOrWhiteSpace($script:PlanPath)) {
        $script:PlanPath = $defaultPlanPath
    }
    foreach ($value in @(
        $ExpectedPlanHash,
        $ExpectedPlanFileSha256,
        $ExpectedApprovalReceiptSha256
    )) {
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Expected plan, plan-file, and receipt SHA256 values are required."
        }
    }
    $resolvedPlanPath = Get-NormalizedPath $script:PlanPath
    Assert-ExactHash (Get-Sha256 $resolvedPlanPath) $ExpectedPlanFileSha256 `
        "plan.file_sha256"
    $plan = Read-JsonFile $resolvedPlanPath
    if ([string]$plan.schema -cne `
        "trading_mvp_slow_liquidity_history_recollect_planonly_v1") {
        throw "Plan schema mismatch."
    }
    Assert-ExactHash ([string]$plan.plan_hash) $ExpectedPlanHash "plan.plan_hash"
    if ([string]$plan.data_quality_after_success.pass_disposition -cne `
        "READY_FOR_SEPARATE_OFFICIAL_IDENTITY_VERIFICATION_ONLY" -or
        [string]$plan.data_quality_after_success.reject_disposition -cne `
        "TERMINAL_DATA_QUALITY_REJECT_NO_RETRY_WITHOUT_NEW_EXACT_APPROVAL" -or
        [bool]$plan.data_quality_after_success.evaluator_or_oos_authorized -or
        [bool]$plan.data_quality_after_success.official_identity_verification_authorized_by_this_plan -or
        [bool]$plan.data_quality_after_success.fixed_signal_plan_allowed_before_identity_verification -or
        [bool]$plan.data_quality_after_success.direct_generic_wrapper_actual_allowed) {
        throw "Plan technical-quality checkpoint is not fail-closed."
    }
    Assert-ExactPath ([string]$plan.commands.data_quality_after_complete_runner) `
        $PSCommandPath "plan exact quality runner"
    Assert-ExactHash (Get-Sha256 $PSCommandPath) `
        ([string]$plan.data_quality_after_success.exact_runner_sha256) `
        "plan exact quality runner SHA256"
    Assert-ExactPath $controlPlaneModule `
        ([string](@($plan.implementation.files | Where-Object {
            [string]$_.role -eq "approval_control_plane"
        })[0].path)) "plan approval control-plane path"
    Assert-ExactPath $qualityWrapper `
        ([string](@($plan.implementation.files | Where-Object {
            [string]$_.role -eq "data_quality_wrapper"
        })[0].path)) "plan data-quality wrapper path"
    Assert-ImplementationBindings -Plan $plan

    $receiptPath = Get-NormalizedPath ([string]$plan.approval_receipt.path)
    Assert-ExactHash (Get-Sha256 $receiptPath) $ExpectedApprovalReceiptSha256 `
        "receipt.file_sha256"
    $launchRecordPath = Get-NormalizedPath ([string]$plan.execution.launch_record_path)
    $manifestPath = Get-NormalizedPath ([string]$plan.execution.manifest_path)
    $outputPath = Get-NormalizedPath ([string]$plan.execution.output_jsonl)
    $qualityOutputPath = Get-NormalizedPath `
        ([string]$plan.data_quality_after_success.output_path)
    foreach ($path in @($launchRecordPath, $manifestPath, $outputPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required exact completed-run file is missing: $path"
        }
    }
    if (Test-Path -LiteralPath $qualityOutputPath) {
        throw "Exact quality output already exists; this step is single-use."
    }
    return [ordered]@{
        plan_path = $resolvedPlanPath
        plan = $plan
        receipt_path = $receiptPath
        launch_record_path = $launchRecordPath
        launch_record_sha256 = Get-Sha256 $launchRecordPath
        manifest_path = $manifestPath
        output_path = $outputPath
        quality_output_path = $qualityOutputPath
        manifest_sha256 = Get-Sha256 $manifestPath
        output_sha256 = Get-Sha256 $outputPath
    }
}

function Invoke-ContextValidation {
    param(
        [Parameter(Mandatory = $true)]$Context,
        [Parameter(Mandatory = $true)]$Guard
    )
    if ([string]$Guard.status -ne "ACTIVE" -or [bool]$Guard.stop_new_actions) {
        throw "Autopilot guard is not open."
    }
    if ([string]$Guard.usage.status -ne "AVAILABLE" -or
        [double]$Guard.usage.remaining_percent -le 15.0 -or
        [string]$Guard.usage.decision -ne "CONTINUE") {
        throw "Weekly telemetry is unavailable, stale, or below the threshold."
    }
    if ([string]$Guard.gate.status -ne "READY_FOR_POSTPROCESS") {
        throw "Active gate is not READY_FOR_POSTPROCESS."
    }
    if (-not (Test-Path -LiteralPath $currentRunPath -PathType Leaf)) {
        throw "Current-run pointer is missing."
    }
    $pointer = Read-JsonFile $currentRunPath
    if (
        [string]$pointer.schema -ne "active_run_pointer_v1" -or
        [string]$pointer.project -ne "trading_mvp" -or
        [string]$pointer.run_id -ne [string]$Context.plan.execution.run_id -or
        [string]$pointer.status -ne "READY_FOR_POSTPROCESS" -or
        [string]$pointer.manifest_path -ine [string]$Context.manifest_path -or
        [string]$pointer.output.path -ine [string]$Context.output_path -or
        @($pointer.process_ids).Count -ne 0 -or
        $null -ne $pointer.collector_pid -or
        $null -ne $pointer.monitor_pid
    ) {
        throw "Current-run pointer does not match the exact terminal recollect."
    }
    if (Test-Path -LiteralPath $globalWriterClaimPath) {
        throw "A global market-data writer claim is active."
    }
    $policySha256 = Get-Sha256 $policyPath
    if ([string]$Guard.policy_hash -cne $policySha256) {
        throw "Guard policy hash does not match the active policy file."
    }
    $raw = & $script:python $controlPlaneModule @(
        "validate-quality",
        "--plan", $Context.plan_path,
        "--expected-plan-file-sha256", $ExpectedPlanFileSha256,
        "--expected-plan-hash", $ExpectedPlanHash,
        "--receipt", $Context.receipt_path,
        "--expected-receipt-file-sha256", $ExpectedApprovalReceiptSha256,
        "--policy", $policyPath,
        "--gate", $gatePath,
        "--launch-record", $Context.launch_record_path,
        "--manifest", $Context.manifest_path,
        "--expected-manifest-file-sha256", $Context.manifest_sha256,
        "--output-jsonl", $Context.output_path,
        "--expected-output-file-sha256", $Context.output_sha256
    ) 2>&1
    $exitCode = $LASTEXITCODE
    $text = (@($raw) -join [Environment]::NewLine).Trim()
    try {
        $validation = $text | ConvertFrom-Json -Depth 100 -DateKind String
    } catch {
        throw "Exact quality-context validator returned invalid JSON."
    }
    if ($exitCode -ne 0 -or [string]$validation.status -ne "VALID") {
        throw "Exact quality context is invalid: $(@($validation.errors) -join ',')."
    }
    return $validation
}

function Assert-ImplementationBindings {
    param([Parameter(Mandatory = $true)]$Plan)
    foreach ($binding in @($Plan.implementation.files)) {
        $path = Get-NormalizedPath ([string]$binding.path)
        Assert-ExactHash (Get-Sha256 $path) ([string]$binding.sha256) `
            "implementation.$([string]$binding.role).sha256"
    }
}

$script:python = Resolve-ProjectPython
$context = Get-Context
$guard = Invoke-Guard
$validation = Invoke-ContextValidation -Context $context -Guard $guard

if ($PreflightOnly) {
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_quality_preflight_v1"
        status = "READY_FOR_EXACT_TECHNICAL_QUALITY"
        would_write = $false
        run_id = [string]$context.plan.execution.run_id
        plan_hash = $ExpectedPlanHash.ToLowerInvariant()
        plan_file_sha256 = $ExpectedPlanFileSha256.ToLowerInvariant()
        receipt_file_sha256 = $ExpectedApprovalReceiptSha256.ToLowerInvariant()
        manifest_file_sha256 = $context.manifest_sha256
        output_file_sha256 = $context.output_sha256
        quality_output_path = $context.quality_output_path
        network_accessed = $false
        evaluator_or_oos_run = $false
        gate_updated = $false
        validation = $validation
    } | ConvertTo-Json -Depth 30
    exit 0
}

$qualityDirectory = Split-Path -Parent $context.quality_output_path
if (-not (Test-Path -LiteralPath $qualityDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $qualityDirectory | Out-Null
}
$temporaryOutput = Join-Path $qualityDirectory (".slow-quality-{0}-{1}.json" -f `
    $PID, [Guid]::NewGuid().ToString("N"))
$originalGateBytes = [System.IO.File]::ReadAllBytes($gatePath)
$originalGateSha256 = Get-Sha256 $gatePath
$originalPointerBytes = [System.IO.File]::ReadAllBytes($currentRunPath)
$originalPointerSha256 = Get-Sha256 $currentRunPath
$outputCommitted = $false
$gateWriteAttempted = $false
$pointerWriteAttempted = $false
try {
    $thresholds = $context.plan.data_quality_after_success.thresholds
    $rawQuality = & pwsh -NoProfile -ExecutionPolicy Bypass -File $qualityWrapper `
        -InputJsonl $context.output_path -ManifestPath $context.manifest_path `
        -OutputPath $temporaryOutput `
        -MinOkRows ([int]$thresholds.min_ok_rows) `
        -MinOkBases ([int]$thresholds.min_ok_bases) `
        -MinOkExchanges ([int]$thresholds.min_ok_exchanges) `
        -MinOkMarketGranularitySlots `
            ([int]$thresholds.min_ok_market_granularity_slots) `
        -MinOkSlotFraction ([double]$thresholds.min_ok_slot_fraction) `
        -MaxApiErrorSlotRate ([double]$thresholds.max_api_error_slot_rate) `
        -MinTwoExchangeBases ([int]$thresholds.min_two_exchange_bases) `
        -MinTwoExchangeFullCoverage1h4hBases `
            ([int]$thresholds.min_two_exchange_full_coverage_1h4h_bases) `
        -MinFullCoverageRatio ([double]$thresholds.min_full_coverage_ratio) `
        -RequireOfficialIdentityAfterQuality `
        -MaxDuplicateCandles ([int]$thresholds.duplicate_candles) -Json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Technical quality process failed: $(@($rawQuality) -join ' ')"
    }
    if (-not (Test-Path -LiteralPath $temporaryOutput -PathType Leaf)) {
        throw "Technical quality process did not create its temporary report."
    }
    $result = Read-JsonFile $temporaryOutput
    if ([string]$result.mode -ne "slow_liquidity_history_data_quality") {
        throw "Technical quality report mode is invalid."
    }
    $expectedConfig = [ordered]@{
        min_ok_rows = [int]$thresholds.min_ok_rows
        min_ok_bases = [int]$thresholds.min_ok_bases
        min_ok_exchanges = [int]$thresholds.min_ok_exchanges
        min_ok_market_granularity_slots = `
            [int]$thresholds.min_ok_market_granularity_slots
        min_ok_slot_fraction = [double]$thresholds.min_ok_slot_fraction
        max_api_error_slot_rate = [double]$thresholds.max_api_error_slot_rate
        min_two_exchange_bases = [int]$thresholds.min_two_exchange_bases
        min_two_exchange_full_coverage_1h4h_bases = `
            [int]$thresholds.min_two_exchange_full_coverage_1h4h_bases
        min_full_coverage_ratio = [double]$thresholds.min_full_coverage_ratio
        max_duplicate_candles = [int]$thresholds.duplicate_candles
    }
    foreach ($entry in $expectedConfig.GetEnumerator()) {
        if ($null -eq $result.config -or
            $result.config.PSObject.Properties.Name -notcontains $entry.Key -or
            [double]$result.config.($entry.Key) -ne [double]$entry.Value) {
            throw "Technical quality report config mismatch: $($entry.Key)."
        }
    }
    if ([bool]$result.replay_allowed -or [bool]$result.grid_allowed -or
        [bool]$result.paper_forward_allowed -or [bool]$result.live_orders -or
        [bool]$result.api_keys -or [bool]$result.leverage_or_margin) {
        throw "Technical quality report opened a forbidden downstream action."
    }
    if ([bool]$result.accepted) {
        if ([string]$result.decision -ne `
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL" -or
            [bool]$result.fixed_signal_plan_allowed -or
            [bool]$result.normalizer_allowed -or
            -not [bool]$result.identity_verification_required -or
            [bool]$result.identity_verification_authorized) {
            throw "Accepted quality report did not preserve the identity checkpoint."
        }
        Set-JsonProperty $result "terminal" $false
    } else {
        if ([string]$result.decision -ne `
            "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE" -or
            [bool]$result.fixed_signal_plan_allowed -or
            [bool]$result.normalizer_allowed) {
            throw "Rejected quality report did not match the bounded technical reject."
        }
        Set-JsonProperty $result "decision" `
            ([string]$context.plan.data_quality_after_success.reject_disposition)
        Set-JsonProperty $result "identity_verification_required" $false
        Set-JsonProperty $result "identity_verification_authorized" $false
        Set-JsonProperty $result "terminal" $true
        Set-JsonProperty $result "next_step_after_ready" `
            "Terminal reject. Do not retry or rescope without a new exact approval."
    }
    Set-JsonProperty $result "retry_authorized" $false
    Set-JsonProperty $result "rescope_authorized" $false
    Set-JsonProperty $result "evaluator_or_oos_authorized" $false
    Set-JsonProperty $result "exact_recollect_provenance" ([ordered]@{
        run_id = [string]$context.plan.execution.run_id
        plan_path = $context.plan_path
        plan_file_sha256 = $ExpectedPlanFileSha256.ToLowerInvariant()
        plan_hash = $ExpectedPlanHash.ToLowerInvariant()
        approval_receipt_path = $context.receipt_path
        approval_receipt_file_sha256 = `
            $ExpectedApprovalReceiptSha256.ToLowerInvariant()
        launch_record_path = $context.launch_record_path
        launch_record_file_sha256 = Get-Sha256 $context.launch_record_path
        manifest_path = $context.manifest_path
        manifest_file_sha256 = $context.manifest_sha256
        output_jsonl_path = $context.output_path
        output_jsonl_file_sha256 = $context.output_sha256
        technical_quality_only = $true
        official_identity_verification_authorized = $false
        evaluator_or_oos_authorized = $false
        stopped_incomplete_retry_authorized = $false
    })
    Set-JsonProperty $result "gate_updated" $true
    Write-JsonAtomic -Path $temporaryOutput -Object $result

    $precommitGuard = Invoke-Guard
    $null = Invoke-ContextValidation -Context $context -Guard $precommitGuard
    Assert-ExactHash (Get-Sha256 $context.manifest_path) $context.manifest_sha256 `
        "precommit manifest SHA256"
    Assert-ExactHash (Get-Sha256 $context.output_path) $context.output_sha256 `
        "precommit output SHA256"
    Assert-ExactHash (Get-Sha256 $context.launch_record_path) `
        $context.launch_record_sha256 "precommit launch-record SHA256"
    Assert-ExactHash (Get-Sha256 $context.plan_path) `
        $ExpectedPlanFileSha256 "precommit plan SHA256"
    Assert-ExactHash (Get-Sha256 $context.receipt_path) `
        $ExpectedApprovalReceiptSha256 "precommit receipt SHA256"
    Assert-ExactHash (Get-Sha256 $policyPath) `
        ([string]$precommitGuard.policy_hash) "precommit policy SHA256"
    Assert-ImplementationBindings -Plan $context.plan

    Move-Item -LiteralPath $temporaryOutput -Destination $context.quality_output_path
    $outputCommitted = $true
    $gate = Read-JsonFile $gatePath
    $accepted = [bool]$result.accepted
    $metrics = $result.metrics
    $nextStep = if ($accepted) {
        "Await separate exact official MEXC/Gate identity approval. Do not run fixed-signal, replay, OOS, evaluator, grid, paper or live steps."
    } else {
        "Terminal data-quality reject for this exact single-use recollect. Do not retry or rescope without new exact approval."
    }
    Set-JsonProperty $gate "updated_at" ([DateTimeOffset]::Now.ToString("o"))
    Set-JsonProperty $gate "next_goal_decision" ([string]$result.decision)
    Set-JsonProperty $gate "next_goal_reason" `
        "Exact recollect technical quality accepted=$accepted; ok_rows=$($metrics.ok_rows), clean_1h4h_two_venue_bases=$($metrics.two_exchange_full_coverage_1h4h_bases)."
    Set-JsonProperty $gate "next_step_after_ready" $nextStep
    Set-JsonProperty $gate "raw_gate_next_step_after_ready" $nextStep
    Set-JsonProperty $gate "replay_allowed" $false
    Set-JsonProperty $gate "grid_allowed" $false
    Set-JsonProperty $gate "paper_forward_allowed" $false
    Set-JsonProperty $gate "identity_verification_required" ([bool]$accepted)
    Set-JsonProperty $gate "identity_verification_authorized" $false
    Set-JsonProperty $gate "last_slow_liquidity_history_data_quality_at" `
        ([DateTimeOffset]::Now.ToString("o"))
    Set-JsonProperty $gate "last_slow_liquidity_history_data_quality_output_path" `
        $context.quality_output_path
    Set-JsonProperty $gate "last_slow_liquidity_history_data_quality_output_sha256" `
        (Get-Sha256 $context.quality_output_path)
    Set-JsonProperty $gate "last_slow_liquidity_history_data_quality_decision" `
        ([string]$result.decision)
    Set-JsonProperty $gate "last_slow_liquidity_history_data_quality_reasons" `
        @($result.reasons)
    Set-JsonProperty $gate "last_slow_liquidity_history_data_quality_warnings" `
        @($result.warnings)
    Set-JsonProperty $gate "strategy_branch_status" ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = if ($accepted) {
            "history_quality_accepted_await_official_identity_approval"
        } else {
            "history_quality_rejected_terminal_no_retry"
        }
        decision_source = $context.quality_output_path
        data_quality_accepted = $accepted
        clean_1h4h_two_venue_bases = `
            $metrics.two_exchange_full_coverage_1h4h_bases
        identity_verification_required = [bool]$accepted
        identity_verification_authorized = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        next_step_required = if ($accepted) {
            "separate_exact_official_identity_approval"
        } else {
            "terminal_reject_no_retry_without_new_exact_approval"
        }
    })
    Assert-ExactHash (Get-Sha256 $gatePath) $originalGateSha256 `
        "precommit active gate SHA256"
    Assert-ExactHash (Get-Sha256 $currentRunPath) $originalPointerSha256 `
        "precommit current-run pointer SHA256"
    $gateWriteAttempted = $true
    Write-JsonAtomic -Path $gatePath -Object $gate
    $pointer = [ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = [string]$context.plan.execution.run_id
        status = "READY_FOR_POSTPROCESS"
        updated_at = [DateTimeOffset]::Now.ToString("o")
        manifest_path = $context.manifest_path
        output = [ordered]@{ path = $context.output_path; kind = "file" }
        collector_pid = $null
        monitor_pid = $null
        process_ids = @()
        launch_record_path = $context.launch_record_path
    }
    $pointerWriteAttempted = $true
    Write-JsonAtomic -Path $currentRunPath -Object $pointer
    Set-JsonProperty $result "quality_output_sha256" `
        (Get-Sha256 $context.quality_output_path)
    $result | ConvertTo-Json -Depth 30
} catch {
    if ($gateWriteAttempted) {
        try {
            Write-BytesAtomic -Path $gatePath -Bytes $originalGateBytes
        } catch {
            Write-Warning "Failed to restore the original active gate."
        }
    }
    if ($pointerWriteAttempted) {
        try {
            Write-BytesAtomic -Path $currentRunPath -Bytes $originalPointerBytes
        } catch {
            Write-Warning "Failed to restore the original current-run pointer."
        }
    }
    if ($outputCommitted) {
        Remove-Item -LiteralPath $context.quality_output_path -Force `
            -ErrorAction SilentlyContinue
    }
    throw
} finally {
    if (Test-Path -LiteralPath $temporaryOutput) {
        Remove-Item -LiteralPath $temporaryOutput -Force -ErrorAction SilentlyContinue
    }
}
