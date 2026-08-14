param(
    [string]$PlanPath = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanHash = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanFileSha256 = "",
    [AllowEmptyString()]
    [string]$UserApprovalText = "",
    [switch]$PreflightOnly,
    [switch]$Apply,
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
$guardScript = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$launcherPath = Join-Path $repoRoot `
    "tools\start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
$controlPlaneModule = Join-Path $repoRoot `
    "trading_mvp\src\slow_liquidity_recollect_control_plane.py"
$globalWriterClaimPath = Join-Path $repoRoot `
    "docs\agent-log\active-market-data-writer-claim.json"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
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
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python runtime not found."
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -DateKind String
}

function Invoke-JsonCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$AllowNonzero
    )
    $raw = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = (@($raw) -join [Environment]::NewLine).Trim()
    if (-not $AllowNonzero -and $exitCode -ne 0) {
        throw "Command failed with exit=$exitCode`: $text"
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "Command returned empty JSON."
    }
    return [ordered]@{
        exit_code = $exitCode
        value = $text | ConvertFrom-Json -DateKind String
    }
}

function Write-FileCreateNew {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $directory = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $sourceBytes = [System.IO.File]::ReadAllBytes($Source)
    $stream = [System.IO.FileStream]::new(
        $Destination,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::Read
    )
    try {
        $stream.Write($sourceBytes, 0, $sourceBytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Write-FileAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $directory = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporary = Join-Path $directory (".{0}.{1}.{2}.tmp" -f (
        [System.IO.Path]::GetFileName($Destination),
        $PID,
        [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    ))
    try {
        [System.IO.File]::WriteAllBytes(
            $temporary,
            [System.IO.File]::ReadAllBytes($Source)
        )
        [System.IO.File]::Move($temporary, $Destination, $true)
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Rollback-AppliedControlPlane {
    param(
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$ReceiptCandidateSha256,
        [Parameter(Mandatory = $true)][string]$PolicyPath,
        [Parameter(Mandatory = $true)][string]$PolicyCandidateSha256,
        [Parameter(Mandatory = $true)][string]$OriginalPolicyPath,
        [Parameter(Mandatory = $true)][string]$GatePath,
        [Parameter(Mandatory = $true)][string]$GateCandidateSha256,
        [Parameter(Mandatory = $true)][string]$OriginalGatePath,
        [Parameter(Mandatory = $true)][bool]$receipt_created_by_this_process,
        [Parameter(Mandatory = $true)][bool]$policy_written_by_this_process,
        [Parameter(Mandatory = $true)][bool]$gate_written_by_this_process
    )
    $rollbackErrors = [System.Collections.Generic.List[string]]::new()
    if ($gate_written_by_this_process) {
        try {
            if (
                -not (Test-Path -LiteralPath $GatePath -PathType Leaf) -or
                (Get-Sha256 $GatePath) -ne $GateCandidateSha256
            ) {
                $rollbackErrors.Add("gate_not_owned_at_rollback")
            } else {
                Write-FileAtomic -Source $OriginalGatePath -Destination $GatePath
            }
        } catch {
            $rollbackErrors.Add("gate_rollback_failed:$($_.Exception.Message)")
        }
    }
    if ($policy_written_by_this_process) {
        try {
            if (
                -not (Test-Path -LiteralPath $PolicyPath -PathType Leaf) -or
                (Get-Sha256 $PolicyPath) -ne $PolicyCandidateSha256
            ) {
                $rollbackErrors.Add("policy_not_owned_at_rollback")
            } else {
                Write-FileAtomic -Source $OriginalPolicyPath -Destination $PolicyPath
            }
        } catch {
            $rollbackErrors.Add("policy_rollback_failed:$($_.Exception.Message)")
        }
    }
    if ($receipt_created_by_this_process) {
        try {
            if (
                -not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) -or
                (Get-Sha256 $ReceiptPath) -ne $ReceiptCandidateSha256
            ) {
                $rollbackErrors.Add("receipt_not_owned_at_rollback")
            } else {
                Remove-Item -LiteralPath $ReceiptPath -Force
            }
        } catch {
            $rollbackErrors.Add("receipt_rollback_failed:$($_.Exception.Message)")
        }
    }
    return @($rollbackErrors)
}

function Get-ExpectedApprovalText {
    param(
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][string]$PlanHash,
        [Parameter(Mandatory = $true)][string]$PlanFileSha256
    )
    $template = [string]$Plan.approval_request.exact_user_text_template
    if (
        ([regex]::Matches($template, [regex]::Escape("<PLAN_HASH>"))).Count -ne 1 -or
        ([regex]::Matches($template, [regex]::Escape("<PLAN_FILE_SHA256>"))).Count -ne 1
    ) {
        throw "Approval text template placeholders are invalid."
    }
    return $template.Replace("<PLAN_HASH>", $PlanHash.ToLowerInvariant()).Replace(
        "<PLAN_FILE_SHA256>", $PlanFileSha256.ToLowerInvariant()
    ).Trim()
}

if ((@($PreflightOnly, $Apply | Where-Object { $_ })).Count -ne 1) {
    throw "Choose exactly one mode: -PreflightOnly or -Apply."
}
if ([string]::IsNullOrWhiteSpace($PlanPath)) { $PlanPath = $defaultPlanPath }
if ([string]::IsNullOrWhiteSpace($ExpectedPlanHash)) {
    throw "ExpectedPlanHash is required."
}
if ([string]::IsNullOrWhiteSpace($ExpectedPlanFileSha256)) {
    throw "ExpectedPlanFileSha256 is required."
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "Plan is missing: $PlanPath"
}
if ((Get-Sha256 $PlanPath) -ne $ExpectedPlanFileSha256.ToLowerInvariant()) {
    throw "Plan file SHA256 mismatch."
}
$plan = Read-JsonFile -Path $PlanPath
if ([string]$plan.plan_hash -ne $ExpectedPlanHash.ToLowerInvariant()) {
    throw "Plan hash mismatch."
}
$expectedApprovalText = Get-ExpectedApprovalText -Plan $plan `
    -PlanHash $ExpectedPlanHash -PlanFileSha256 $ExpectedPlanFileSha256
$python = Resolve-ProjectPython

$launcherPreflight = Invoke-JsonCommand -FilePath "pwsh" -Arguments @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcherPath,
    "-PlanPath", $PlanPath,
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-ExpectedPlanFileSha256", $ExpectedPlanFileSha256,
    "-PreflightOnly", "-Json"
)
$allowedPreflightReasons = @("exact_approval_receipt_missing")
$unexpectedPreflightReasons = @(
    $launcherPreflight.value.reasons | Where-Object { $_ -notin $allowedPreflightReasons }
)

$guardResult = Invoke-JsonCommand -FilePath "pwsh" -Arguments @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $guardScript, "-Json"
)
$guard = $guardResult.value
$receiptPath = [System.IO.Path]::GetFullPath([string]$plan.approval_receipt.path)
$launchRecordPath = [System.IO.Path]::GetFullPath([string]$plan.execution.launch_record_path)
$outputPath = [System.IO.Path]::GetFullPath([string]$plan.execution.output_path)
$blockers = [System.Collections.Generic.List[string]]::new()
if ([string]$guard.status -ne "ACTIVE") { $blockers.Add("guard_not_active") }
if ([bool]$guard.stop_new_actions) { $blockers.Add("guard_stops_new_actions") }
if ([string]$guard.usage.status -ne "AVAILABLE") { $blockers.Add("usage_unavailable") }
if ([double]$guard.usage.remaining_percent -le 15.0) { $blockers.Add("weekly_limit") }
if ([string]$guard.usage.decision -ne "CONTINUE") { $blockers.Add("usage_guard_blocked") }
if ([string]$guard.gate.status -ne "READY_FOR_POSTPROCESS") {
    $blockers.Add("gate_not_ready_for_postprocess")
}
if (
    [string]$guard.gate.next_goal_decision -ne
    [string]$plan.guard_contract.preapproval_decision
) {
    $blockers.Add("preapproval_gate_decision_mismatch")
}
foreach ($reason in $unexpectedPreflightReasons) { $blockers.Add([string]$reason) }
if (Test-Path -LiteralPath $receiptPath) { $blockers.Add("receipt_already_exists") }
if (Test-Path -LiteralPath $launchRecordPath) { $blockers.Add("launch_record_exists") }
if (Test-Path -LiteralPath $outputPath) { $blockers.Add("output_namespace_exists") }
if (Test-Path -LiteralPath $globalWriterClaimPath) {
    $blockers.Add("global_writer_claim_exists")
}
$activePolicySha256 = Get-Sha256 $policyPath
$activeGateSha256 = Get-Sha256 $gatePath
if ($activePolicySha256 -ne [string]$guard.policy_hash) {
    $blockers.Add("active_policy_hash_mismatch")
}
if (
    $activePolicySha256 -ne
    [string]$plan.guard_contract.preapproval_policy_file_sha256
) {
    $blockers.Add("preapproval_policy_hash_mismatch")
}
if (
    [string]$guard.policy_id -ne
    [string]$plan.guard_contract.preapproval_policy_id
) {
    $blockers.Add("preapproval_policy_id_mismatch")
}

$normalizedUserText = $UserApprovalText.Replace("`r`n", "`n").Replace("`r", "`n").Trim()
$approvalTextMatches = (
    -not [string]::IsNullOrWhiteSpace($normalizedUserText) -and
    $normalizedUserText -ceq $expectedApprovalText
)
if ($Apply -and -not $approvalTextMatches) {
    $blockers.Add("exact_user_approval_text_mismatch")
}

if ($PreflightOnly -and -not $approvalTextMatches) {
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_approval_freeze_preflight_v1"
        status = "AWAIT_EXACT_USER_APPROVAL"
        would_write = $false
        blockers = @($blockers)
        plan_path = $PlanPath
        plan_file_sha256 = $ExpectedPlanFileSha256.ToLowerInvariant()
        plan_hash = $ExpectedPlanHash.ToLowerInvariant()
        expected_user_approval_text = $expectedApprovalText
        receipt_path = $receiptPath
        active_policy_path = $policyPath
        active_gate_path = $gatePath
        network_accessed = $false
        collector_started = $false
        output_created = $false
    } | ConvertTo-Json -Depth 12
    exit 0
}
if ($blockers.Count -gt 0) {
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_approval_freeze_preflight_v1"
        status = "BLOCKED"
        would_write = $false
        blockers = @($blockers)
        plan_path = $PlanPath
        receipt_path = $receiptPath
        network_accessed = $false
        collector_started = $false
        output_created = $false
    } | ConvertTo-Json -Depth 12
    exit 2
}

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "slow-liquidity-recollect-approval-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    $approvalTextPath = Join-Path $temporaryRoot "approval.txt"
    $receiptCandidate = Join-Path $temporaryRoot "receipt.json"
    $policyCandidate = Join-Path $temporaryRoot "policy.json"
    $gateCandidate = Join-Path $temporaryRoot "gate.json"
    $originalPolicyPath = Join-Path $temporaryRoot "original-policy.json"
    $originalGatePath = Join-Path $temporaryRoot "original-gate.json"
    [System.IO.File]::WriteAllBytes(
        $originalPolicyPath,
        [System.IO.File]::ReadAllBytes($policyPath)
    )
    [System.IO.File]::WriteAllBytes(
        $originalGatePath,
        [System.IO.File]::ReadAllBytes($gatePath)
    )
    $sourcePolicySha256 = Get-Sha256 $originalPolicyPath
    $sourceGateSha256 = Get-Sha256 $originalGatePath
    if (
        $sourcePolicySha256 -ne $activePolicySha256 -or
        $sourceGateSha256 -ne $activeGateSha256
    ) {
        throw "precommit_source_state_changed: snapshot_mismatch"
    }
    [System.IO.File]::WriteAllText(
        $approvalTextPath,
        $normalizedUserText,
        [System.Text.UTF8Encoding]::new($false)
    )
    $render = Invoke-JsonCommand -FilePath $python -Arguments @(
        $controlPlaneModule, "render",
        "--plan", $PlanPath,
        "--expected-plan-file-sha256", $ExpectedPlanFileSha256,
        "--expected-plan-hash", $ExpectedPlanHash,
        "--policy", $originalPolicyPath,
        "--gate", $originalGatePath,
        "--user-approval-text-file", $approvalTextPath,
        "--receipt-output", $receiptCandidate,
        "--policy-output", $policyCandidate,
        "--gate-output", $gateCandidate,
        "--approved-at-utc", [DateTimeOffset]::UtcNow.ToString("o")
    )
    if ([string]$render.value.status -ne "CANDIDATE_BUNDLE_RENDERED") {
        throw "Control-plane renderer did not return a candidate bundle."
    }
    $candidateValidation = Invoke-JsonCommand -FilePath $python -Arguments @(
        $controlPlaneModule, "validate",
        "--plan", $PlanPath,
        "--expected-plan-file-sha256", $ExpectedPlanFileSha256,
        "--expected-plan-hash", $ExpectedPlanHash,
        "--receipt", $receiptCandidate,
        "--logical-receipt-path", $receiptPath,
        "--expected-receipt-file-sha256", [string]$render.value.receipt_file_sha256,
        "--policy", $policyCandidate,
        "--gate", $gateCandidate
    )
    if ([string]$candidateValidation.value.status -ne "VALID") {
        throw "Rendered control-plane candidate failed validation."
    }

    $precommitLauncher = Invoke-JsonCommand -FilePath "pwsh" -Arguments @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcherPath,
        "-PlanPath", $PlanPath,
        "-ExpectedPlanHash", $ExpectedPlanHash,
        "-ExpectedPlanFileSha256", $ExpectedPlanFileSha256,
        "-PreflightOnly", "-Json"
    )
    $precommitGuardResult = Invoke-JsonCommand -FilePath "pwsh" -Arguments @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $guardScript, "-Json"
    )
    $precommitGuard = $precommitGuardResult.value
    $precommitReasons = [System.Collections.Generic.List[string]]::new()
    $precommitLauncherReasons = @($precommitLauncher.value.reasons)
    if (
        [string]$precommitLauncher.value.status -ne "BLOCKED_AWAITING_EXACT_APPROVAL" -or
        $precommitLauncherReasons.Count -ne 1 -or
        [string]$precommitLauncherReasons[0] -ne "exact_approval_receipt_missing"
    ) {
        $precommitReasons.Add("launcher_preflight_changed")
    }
    if (
        [string]$precommitGuard.status -ne "ACTIVE" -or
        [bool]$precommitGuard.stop_new_actions -or
        [string]$precommitGuard.usage.status -ne "AVAILABLE" -or
        [double]$precommitGuard.usage.remaining_percent -le 15.0 -or
        [string]$precommitGuard.usage.decision -ne "CONTINUE" -or
        [string]$precommitGuard.gate.status -ne "READY_FOR_POSTPROCESS" -or
        [string]$precommitGuard.gate.next_goal_decision -ne
            [string]$plan.guard_contract.preapproval_decision -or
        [string]$precommitGuard.policy_id -ne
            [string]$plan.guard_contract.preapproval_policy_id
    ) {
        $precommitReasons.Add("fresh_guard_changed")
    }
    if (
        (Get-Sha256 $PlanPath) -ne $ExpectedPlanFileSha256.ToLowerInvariant() -or
        (Get-Sha256 $policyPath) -ne $sourcePolicySha256 -or
        (Get-Sha256 $gatePath) -ne $sourceGateSha256 -or
        [string]$precommitGuard.policy_hash -ne $sourcePolicySha256
    ) {
        $precommitReasons.Add("bound_source_hash_changed")
    }
    if (
        (Test-Path -LiteralPath $receiptPath) -or
        (Test-Path -LiteralPath $launchRecordPath) -or
        (Test-Path -LiteralPath $outputPath) -or
        (Test-Path -LiteralPath $globalWriterClaimPath)
    ) {
        $precommitReasons.Add("single_use_or_writer_state_changed")
    }
    if ($precommitReasons.Count -gt 0) {
        throw "precommit_source_state_changed: $($precommitReasons -join ',')"
    }

    if ($PreflightOnly) {
        [ordered]@{
            schema = "trading_mvp_slow_liquidity_recollect_approval_freeze_preflight_v1"
            status = "READY_TO_FREEZE_AFTER_EXACT_USER_APPROVAL"
            would_write = $false
            blockers = @()
            plan_path = $PlanPath
            plan_file_sha256 = $ExpectedPlanFileSha256.ToLowerInvariant()
            plan_hash = $ExpectedPlanHash.ToLowerInvariant()
            candidate_receipt_sha256 = [string]$render.value.receipt_file_sha256
            candidate_policy_sha256 = [string]$render.value.policy_file_sha256
            candidate_gate_sha256 = [string]$render.value.gate_file_sha256
            precommit_guard_rechecked = $true
            precommit_source_hashes_rechecked = $true
            network_accessed = $false
            collector_started = $false
            output_created = $false
        } | ConvertTo-Json -Depth 12
        exit 0
    }

    $receipt_created_by_this_process = $false
    $policy_written_by_this_process = $false
    $gate_written_by_this_process = $false
    try {
        Write-FileCreateNew -Source $receiptCandidate -Destination $receiptPath
        $receipt_created_by_this_process = $true
        if (
            (Get-Sha256 $policyPath) -ne $sourcePolicySha256 -or
            (Get-Sha256 $gatePath) -ne $sourceGateSha256 -or
            (Test-Path -LiteralPath $globalWriterClaimPath)
        ) {
            throw "precommit_source_state_changed: after_receipt_claim"
        }
        Write-FileAtomic -Source $policyCandidate -Destination $policyPath
        $policy_written_by_this_process = $true
        if ((Get-Sha256 $gatePath) -ne $sourceGateSha256) {
            throw "precommit_source_state_changed: before_gate_write"
        }
        Write-FileAtomic -Source $gateCandidate -Destination $gatePath
        $gate_written_by_this_process = $true

        $freshGuardResult = Invoke-JsonCommand -FilePath "pwsh" -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $guardScript, "-Json"
        )
        $freshGuard = $freshGuardResult.value
        if (
            [string]$freshGuard.status -ne "ACTIVE" -or
            [string]$freshGuard.policy_hash -ne [string]$render.value.policy_file_sha256 -or
            [string]$freshGuard.gate.next_goal_decision -ne
                [string]$plan.guard_contract.required_decision_after_approval
        ) {
            throw "Fresh guard did not confirm the exact policy/gate rebind."
        }
        $finalValidation = Invoke-JsonCommand -FilePath $python -Arguments @(
            $controlPlaneModule, "validate",
            "--plan", $PlanPath,
            "--expected-plan-file-sha256", $ExpectedPlanFileSha256,
            "--expected-plan-hash", $ExpectedPlanHash,
            "--receipt", $receiptPath,
            "--expected-receipt-file-sha256", [string]$render.value.receipt_file_sha256,
            "--policy", $policyPath,
            "--gate", $gatePath
        )
        if ([string]$finalValidation.value.status -ne "VALID") {
            throw "Applied control-plane rebind failed validation."
        }
    } catch {
        $applyFailure = $_.Exception.Message
        $rollbackErrors = Rollback-AppliedControlPlane `
            -ReceiptPath $receiptPath `
            -ReceiptCandidateSha256 ([string]$render.value.receipt_file_sha256) `
            -PolicyPath $policyPath `
            -PolicyCandidateSha256 ([string]$render.value.policy_file_sha256) `
            -OriginalPolicyPath $originalPolicyPath `
            -GatePath $gatePath `
            -GateCandidateSha256 ([string]$render.value.gate_file_sha256) `
            -OriginalGatePath $originalGatePath `
            -receipt_created_by_this_process $receipt_created_by_this_process `
            -policy_written_by_this_process $policy_written_by_this_process `
            -gate_written_by_this_process $gate_written_by_this_process
        if (@($rollbackErrors).Count -gt 0) {
            throw "$applyFailure Rollback incomplete: $($rollbackErrors -join ';')"
        }
        throw
    }
    [ordered]@{
        schema = "trading_mvp_slow_liquidity_recollect_approval_freeze_v1"
        status = "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
        plan_path = $PlanPath
        plan_file_sha256 = $ExpectedPlanFileSha256.ToLowerInvariant()
        plan_hash = $ExpectedPlanHash.ToLowerInvariant()
        approval_receipt_path = $receiptPath
        approval_receipt_sha256 = [string]$render.value.receipt_file_sha256
        active_policy_path = $policyPath
        active_policy_sha256 = [string]$render.value.policy_file_sha256
        active_gate_path = $gatePath
        guard_decision = [string]$freshGuard.gate.next_goal_decision
        collector_started = $false
        network_accessed = $false
        output_created = $false
    } | ConvertTo-Json -Depth 12
    exit 0
} finally {
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
}
