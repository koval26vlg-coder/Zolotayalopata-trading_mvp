param(
    [string]$PlanPath = "",
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanHash = "",
    [string]$PolicyPath = "",
    [switch]$PreflightOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frozenLauncher = Join-Path $projectRoot "tools\start_dense_ws_campaign_visible.ps1"
$guardScript = Join-Path $projectRoot "tools\check_trading_mvp_autopilot.ps1"
$runtimeDependencyChecker = Join-Path $projectRoot `
    "tools\check_dense_ws_runtime_dependencies.ps1"
$expectedRuntimeDependencyCheckerSha256 = `
    "b0380b1a4806619290d9c7001cefa86994824a57fd8320daac7cbf8eb3f6ab51"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ExactString {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]$Actual -cne [string]$Expected) {
        throw "$Label mismatch."
    }
}

function Assert-ExactHash {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (
        [string]$Actual -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$Expected -notmatch "^[0-9a-fA-F]{64}$" -or
        ([string]$Actual).ToLowerInvariant() -ne ([string]$Expected).ToLowerInvariant()
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

function Assert-ExactBoolean {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][bool]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([bool]$Actual -ne $Expected) {
        throw "$Label mismatch."
    }
}

function Assert-ExactInt64 {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][long]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([long]$Actual -ne $Expected) {
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

function Assert-DenseWsExactLaunchApproval {
    param(
        [Parameter(Mandatory = $true)]$Policy,
        [Parameter(Mandatory = $true)]$Guard,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)]$Receipt,
        [Parameter(Mandatory = $true)][string]$PolicyFileSha256,
        [Parameter(Mandatory = $true)][string]$PlanPath,
        [Parameter(Mandatory = $true)][string]$PlanFileSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$ReceiptFileSha256,
        [Parameter(Mandatory = $true)][string]$FrozenLauncherPath,
        [Parameter(Mandatory = $true)][string]$FrozenLauncherSha256
    )

    $candidate = $Policy.next_long_campaign
    $policyApproval = $candidate.user_launch_approval
    $guardCandidate = $Guard.long_campaign_candidate
    $guardCandidateApproval = $guardCandidate.user_launch_approval
    $guardApproval = $Guard.long_campaign_approval

    Assert-ExactString $Guard.schema "trading_mvp_autopilot_state_v1" "guard.schema"
    Assert-ExactString $Guard.status "ACTIVE" "guard.status"
    Assert-ExactBoolean $Guard.stop_new_actions $false "guard.stop_new_actions"
    Assert-ExactString $Guard.usage.status "AVAILABLE" "guard.usage.status"
    if ([double]$Guard.usage.remaining_percent -le 15.0) {
        throw "guard.usage.remaining_percent must exceed 15."
    }
    Assert-ExactHash $Guard.policy_hash $PolicyFileSha256 "guard.policy_hash"
    Assert-ExactString $Receipt.thread_id $Policy.thread_id "receipt.thread_id"

    Assert-ExactString $candidate.status "READY_FOR_APPROVAL" "policy.candidate.status"
    Assert-ExactString $guardCandidate.status "READY_FOR_APPROVAL" "guard.candidate.status"
    Assert-ExactString $guardApproval.status "APPROVED" "guard.approval.status"
    Assert-ExactString $policyApproval.status "APPROVED" "policy.approval.status"
    Assert-ExactString $guardCandidateApproval.status "APPROVED" "guard.candidate.approval.status"

    Assert-ExactString $Plan.schema "trading_mvp_dense_ws_campaign_planonly_v1" "plan.schema"
    Assert-ExactString $Plan.approval_state "NOT_APPROVED" "plan.approval_state"
    Assert-ExactBoolean $Plan.actual_collection_allowed $false "plan.actual_collection_allowed"
    Assert-ExactString $Plan.launch_controls.status "READY_FOR_SEPARATE_EXACT_APPROVAL" "plan.launch_controls.status"
    Assert-ExactBoolean $Plan.launch_controls.separate_exact_user_approval_required $true "plan.separate_exact_user_approval_required"
    Assert-ExactBoolean $Plan.launch_controls.stop_incomplete_recovery_requires_new_exact_approval $true "plan.stop_incomplete_recovery_requires_new_exact_approval"
    Assert-ExactBoolean $Plan.launch_controls.visible_terminal_required $true "plan.visible_terminal_required"
    Assert-ExactBoolean $Plan.launch_controls.single_writer $true "plan.single_writer"

    Assert-ExactHash $Plan.plan_hash $ExpectedPlanHash "plan.plan_hash"
    Assert-ExactPath $candidate.plan_path $PlanPath "policy.candidate.plan_path"
    Assert-ExactPath $guardCandidate.plan_path $PlanPath "guard.candidate.plan_path"
    Assert-ExactPath $guardApproval.plan_path $PlanPath "guard.approval.plan_path"
    Assert-ExactPath $Receipt.plan_path $PlanPath "receipt.plan_path"
    Assert-ExactHash $candidate.plan_file_sha256 $PlanFileSha256 "policy.candidate.plan_file_sha256"
    Assert-ExactHash $guardCandidate.plan_file_sha256 $PlanFileSha256 "guard.candidate.plan_file_sha256"
    Assert-ExactHash $guardApproval.plan_file_sha256 $PlanFileSha256 "guard.approval.plan_file_sha256"
    Assert-ExactHash $Receipt.plan_file_sha256 $PlanFileSha256 "receipt.plan_file_sha256"

    foreach ($binding in @(
        @{ Value = $candidate.campaign_id; Label = "policy.candidate.campaign_id" },
        @{ Value = $policyApproval.campaign_id; Label = "policy.approval.campaign_id" },
        @{ Value = $guardCandidate.campaign_id; Label = "guard.candidate.campaign_id" },
        @{ Value = $guardCandidateApproval.campaign_id; Label = "guard.candidate.approval.campaign_id" },
        @{ Value = $guardApproval.campaign_id; Label = "guard.approval.campaign_id" },
        @{ Value = $Receipt.campaign_id; Label = "receipt.campaign_id" }
    )) {
        Assert-ExactString $binding.Value $Plan.campaign_id $binding.Label
    }
    foreach ($binding in @(
        @{ Value = $candidate.plan_hash; Label = "policy.candidate.plan_hash" },
        @{ Value = $policyApproval.plan_hash; Label = "policy.approval.plan_hash" },
        @{ Value = $guardCandidate.plan_hash; Label = "guard.candidate.plan_hash" },
        @{ Value = $guardCandidateApproval.plan_hash; Label = "guard.candidate.approval.plan_hash" },
        @{ Value = $guardApproval.plan_hash; Label = "guard.approval.plan_hash" },
        @{ Value = $Receipt.plan_hash; Label = "receipt.plan_hash" }
    )) {
        Assert-ExactHash $binding.Value $ExpectedPlanHash $binding.Label
    }

    Assert-ExactPath $policyApproval.receipt_path $ReceiptPath "policy.approval.receipt_path"
    Assert-ExactPath $guardCandidateApproval.receipt_path $ReceiptPath "guard.candidate.approval.receipt_path"
    Assert-ExactPath $guardApproval.receipt_path $ReceiptPath "guard.approval.receipt_path"
    Assert-ExactHash $policyApproval.receipt_sha256 $ReceiptFileSha256 "policy.approval.receipt_sha256"
    Assert-ExactHash $guardCandidateApproval.receipt_sha256 $ReceiptFileSha256 "guard.candidate.approval.receipt_sha256"
    Assert-ExactHash $guardApproval.receipt_sha256 $ReceiptFileSha256 "guard.approval.receipt_sha256"

    Assert-ExactString $Receipt.schema "trading_mvp_long_campaign_approval_v1" "receipt.schema"
    Assert-ExactString $Receipt.status "APPROVED" "receipt.status"
    Assert-ExactString $Receipt.approval_type "EXACT_HASH_BOUND_VISIBLE_LONG_CAMPAIGN" "receipt.approval_type"
    Assert-ExactString $Receipt.approved_at_utc $policyApproval.approved_at_utc "receipt.approved_at_utc"
    Assert-ExactString $Receipt.approved_at_utc $guardApproval.approved_at_utc "receipt/guard.approved_at_utc"
    Assert-ExactBoolean $Receipt.single_use $true "receipt.single_use"
    Assert-ExactBoolean $policyApproval.single_use $true "policy.approval.single_use"
    Assert-ExactBoolean $guardCandidateApproval.single_use $true "guard.candidate.approval.single_use"
    Assert-ExactBoolean $guardApproval.single_use $true "guard.approval.single_use"
    Assert-ExactBoolean $Receipt.stop_incomplete_recovery_authorized $false "receipt.stop_incomplete_recovery_authorized"
    Assert-ExactBoolean $policyApproval.stop_incomplete_recovery_authorized $false "policy.approval.stop_incomplete_recovery_authorized"
    Assert-ExactBoolean $guardCandidateApproval.stop_incomplete_recovery_authorized $false "guard.candidate.approval.stop_incomplete_recovery_authorized"
    Assert-ExactBoolean $guardApproval.stop_incomplete_recovery_authorized $false "guard.approval.stop_incomplete_recovery_authorized"

    Assert-ExactPath $Receipt.contract_path $candidate.contract_path "receipt.contract_path"
    Assert-ExactHash $Receipt.contract_file_sha256 $candidate.contract_file_sha256 "receipt.contract_file_sha256"
    Assert-ExactHash $Receipt.contract_hash $candidate.contract_hash "receipt.contract_hash"
    Assert-ExactString $Receipt.writer_start_local $Plan.window.start_local "receipt.writer_start_local"
    Assert-ExactString $Receipt.writer_start_local $candidate.start_local "receipt/policy.writer_start_local"
    Assert-ExactString $Receipt.writer_deadline_local $Plan.window.writer_deadline_local "receipt.writer_deadline_local"
    Assert-ExactString $Receipt.writer_deadline_local $candidate.writer_deadline_local "receipt/policy.writer_deadline_local"
    Assert-ExactString $Receipt.hard_deadline_local $Plan.window.hard_deadline_local "receipt.hard_deadline_local"
    Assert-ExactString $Receipt.hard_deadline_local $candidate.hard_deadline_local "receipt/policy.hard_deadline_local"
    Assert-ExactString $Receipt.earliest_launch_local $guardApproval.earliest_launch_local "receipt.earliest_launch_local"
    Assert-ExactString $Receipt.latest_launch_local $guardApproval.latest_launch_local "receipt.latest_launch_local"
    Assert-ExactInt64 $Receipt.target_writer_sec ([long]$Plan.window.target_writer_sec) "receipt.target_writer_sec"
    Assert-ExactInt64 $Receipt.target_writer_sec ([long]$candidate.target_writer_sec) "receipt/policy.target_writer_sec"
    Assert-ExactInt64 $Receipt.max_runtime_sec ([long]$Plan.window.max_runtime_sec) "receipt.max_runtime_sec"
    Assert-ExactInt64 $Receipt.max_runtime_sec ([long]$candidate.max_runtime_sec) "receipt/policy.max_runtime_sec"
    Assert-ExactInt64 $Receipt.hard_output_cap_bytes ([long]$Plan.resources.hard_output_cap_bytes) "receipt.hard_output_cap_bytes"
    Assert-ExactInt64 $Receipt.hard_output_cap_bytes ([long]$candidate.hard_output_cap_bytes) "receipt/policy.hard_output_cap_bytes"
    Assert-ExactStringArray $Receipt.suppressed_pit_run_ids @($candidate.suppressed_pit_run_ids) "receipt.suppressed_pit_run_ids"

    Assert-ExactStringArray $Receipt.allowed_actions @(
        "one visible public read-only MEXC/Gate network collector",
        "same-hash campaign data-quality checks",
        "same-hash causal materialization"
    ) "receipt.allowed_actions"
    Assert-ExactStringArray $Receipt.forbidden_actions @(
        "live orders",
        "private API keys",
        "real capital",
        "leverage or margin",
        "grid or retune",
        "returns or PnL before frozen gates",
        "OOS before frozen gates"
    ) "receipt.forbidden_actions"
    if ([string]::IsNullOrWhiteSpace([string]$Receipt.approval_text)) {
        throw "receipt.approval_text is missing."
    }

    Assert-ExactPath $Plan.launch_controls.tools.launcher.path $FrozenLauncherPath "plan.launcher.path"
    Assert-ExactHash $Plan.launch_controls.tools.launcher.sha256 $FrozenLauncherSha256 "plan.launcher.sha256"

    return [ordered]@{
        campaign_id = [string]$Plan.campaign_id
        plan_hash = $ExpectedPlanHash.ToLowerInvariant()
        plan_file_sha256 = $PlanFileSha256.ToLowerInvariant()
        receipt_path = $ReceiptPath
        receipt_sha256 = $ReceiptFileSha256.ToLowerInvariant()
        frozen_launcher_path = $FrozenLauncherPath
        frozen_launcher_sha256 = $FrozenLauncherSha256.ToLowerInvariant()
        single_use = $true
        stop_incomplete_recovery_authorized = $false
    }
}

function Invoke-JsonPowerShellFile {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $raw = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $rawText = $raw | Out-String
    if ($exitCode -ne 0) {
        throw "Child script failed with exit code $exitCode`: $rawText"
    }
    try {
        return $rawText | ConvertFrom-Json -DateKind String
    } catch {
        throw "Child script did not return valid JSON: $rawText"
    }
}

function Invoke-DenseWsApprovalGatewayMain {
    if ([string]::IsNullOrWhiteSpace($PlanPath)) {
        throw "PlanPath is required."
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedPlanHash)) {
        throw "ExpectedPlanHash is required."
    }
    if ([string]::IsNullOrWhiteSpace($PolicyPath)) {
        $script:PolicyPath = Join-Path $projectRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
    }

    $resolvedPlanPath = Get-NormalizedPath -Path $PlanPath
    $resolvedPolicyPath = Get-NormalizedPath -Path $PolicyPath
    $resolvedFrozenLauncher = Get-NormalizedPath -Path $frozenLauncher
    $resolvedGuardScript = Get-NormalizedPath -Path $guardScript
    $resolvedRuntimeDependencyChecker = `
        Get-NormalizedPath -Path $runtimeDependencyChecker
    $normalizedPlanHash = $ExpectedPlanHash.ToLowerInvariant()
    foreach ($required in @(
        $resolvedPlanPath,
        $resolvedPolicyPath,
        $resolvedFrozenLauncher,
        $resolvedGuardScript,
        $resolvedRuntimeDependencyChecker
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required file is missing: $required"
        }
    }

    $policy = Get-Content -Raw -LiteralPath $resolvedPolicyPath |
        ConvertFrom-Json -DateKind String
    $plan = Get-Content -Raw -LiteralPath $resolvedPlanPath |
        ConvertFrom-Json -DateKind String
    $guard = Invoke-JsonPowerShellFile -ScriptPath $resolvedGuardScript -Arguments @("-Json")
    $receiptPath = Get-NormalizedPath -Path ([string]$policy.next_long_campaign.user_launch_approval.receipt_path)
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "Approval receipt is missing: $receiptPath"
    }
    $receipt = Get-Content -Raw -LiteralPath $receiptPath |
        ConvertFrom-Json -DateKind String

    $approval = Assert-DenseWsExactLaunchApproval `
        -Policy $policy `
        -Guard $guard `
        -Plan $plan `
        -Receipt $receipt `
        -PolicyFileSha256 (Get-Sha256 -Path $resolvedPolicyPath) `
        -PlanPath $resolvedPlanPath `
        -PlanFileSha256 (Get-Sha256 -Path $resolvedPlanPath) `
        -ExpectedPlanHash $normalizedPlanHash `
        -ReceiptPath $receiptPath `
        -ReceiptFileSha256 (Get-Sha256 -Path $receiptPath) `
        -FrozenLauncherPath $resolvedFrozenLauncher `
        -FrozenLauncherSha256 (Get-Sha256 -Path $resolvedFrozenLauncher)

    Assert-ExactHash `
        (Get-Sha256 -Path $resolvedRuntimeDependencyChecker) `
        $expectedRuntimeDependencyCheckerSha256 `
        "runtime_dependency_checker.sha256"
    $runtimeReadiness = Invoke-JsonPowerShellFile `
        -ScriptPath $resolvedRuntimeDependencyChecker `
        -Arguments @(
            "-PlanPath", $resolvedPlanPath,
            "-ExpectedPlanHash", $normalizedPlanHash,
            "-Json"
        )
    Assert-ExactString $runtimeReadiness.status "READY" `
        "runtime_dependency_readiness.status"
    Assert-ExactString $runtimeReadiness.campaign_id $approval.campaign_id `
        "runtime_dependency_readiness.campaign_id"
    Assert-ExactHash $runtimeReadiness.plan_hash $approval.plan_hash `
        "runtime_dependency_readiness.plan_hash"
    Assert-ExactBoolean $runtimeReadiness.no_run_or_output_writes $true `
        "runtime_dependency_readiness.no_run_or_output_writes"
    Assert-ExactBoolean $runtimeReadiness.network_request_performed $false `
        "runtime_dependency_readiness.network_request_performed"
    Assert-ExactBoolean $runtimeReadiness.writer_started $false `
        "runtime_dependency_readiness.writer_started"

    $launcherArguments = @(
        "-PlanPath", $resolvedPlanPath,
        "-ExpectedPlanHash", $normalizedPlanHash,
        "-PolicyPath", $resolvedPolicyPath,
        "-Json"
    )
    if ($PreflightOnly) {
        $launcherArguments += "-PreflightOnly"
        $inner = Invoke-JsonPowerShellFile `
            -ScriptPath $resolvedFrozenLauncher `
            -Arguments $launcherArguments
        $result = [ordered]@{
            schema = "trading_mvp_dense_ws_approved_launch_gateway_v1"
            status = "EXACT_APPROVAL_VALIDATED_PREFLIGHT_ONLY"
            authorization_verified = $true
            no_run_or_output_writes = $true
            campaign_id = $approval.campaign_id
            plan_hash = $approval.plan_hash
            receipt_path = $approval.receipt_path
            receipt_sha256 = $approval.receipt_sha256
            frozen_launcher_path = $approval.frozen_launcher_path
            frozen_launcher_sha256 = $approval.frozen_launcher_sha256
            runtime_dependency_checker_path = $resolvedRuntimeDependencyChecker
            runtime_dependency_checker_sha256 = `
                $expectedRuntimeDependencyCheckerSha256
            runtime_dependency_readiness = $runtimeReadiness
            can_launch_now = [bool]$inner.can_launch_now
            underlying_status = [string]$inner.status
            underlying_preflight = $inner
        }
    } else {
        $launcherArguments += "-ConfirmedLongCampaign"
        $inner = Invoke-JsonPowerShellFile `
            -ScriptPath $resolvedFrozenLauncher `
            -Arguments $launcherArguments
        Assert-ExactString $inner.status "VISIBLE_TERMINAL_LAUNCHED" "launcher.status"
        Assert-ExactString $inner.campaign_id $approval.campaign_id "launcher.campaign_id"
        Assert-ExactHash $inner.plan_hash $approval.plan_hash "launcher.plan_hash"
        Assert-ExactBoolean $inner.terminal_ownership_verified $true "launcher.terminal_ownership_verified"
        $result = [ordered]@{
            schema = "trading_mvp_dense_ws_approved_launch_gateway_v1"
            status = "VISIBLE_TERMINAL_LAUNCHED"
            authorization_verified = $true
            campaign_id = $approval.campaign_id
            run_id = [string]$inner.run_id
            plan_hash = $approval.plan_hash
            receipt_path = $approval.receipt_path
            receipt_sha256 = $approval.receipt_sha256
            frozen_launcher_path = $approval.frozen_launcher_path
            frozen_launcher_sha256 = $approval.frozen_launcher_sha256
            runtime_dependency_checker_path = $resolvedRuntimeDependencyChecker
            runtime_dependency_checker_sha256 = `
                $expectedRuntimeDependencyCheckerSha256
            runtime_dependency_readiness = $runtimeReadiness
            terminal_pid = [int]$inner.terminal_pid
            terminal_ownership_verified = $true
            reservation_path = [string]$inner.reservation_path
            status_command = [string]$inner.status_command
            stop_command = [string]$inner.stop_command
            single_use = $true
            stop_incomplete_recovery_authorized = $false
        }
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 30
    } else {
        $result | Format-List
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-DenseWsApprovalGatewayMain
}
