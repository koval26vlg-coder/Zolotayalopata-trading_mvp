param(
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-microstructure-regime-filter-planonly-20260803-aef-24h-v1.json",
    [string]$ExpectedPlanHash = "57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b",
    [string]$PolicyPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateway = Join-Path $PSScriptRoot "start_exact_approved_dense_ws_campaign_visible.ps1"
$guardScript = Join-Path $PSScriptRoot "check_trading_mvp_autopilot.ps1"
$frozenLauncher = Join-Path $PSScriptRoot "start_dense_ws_campaign_visible.ps1"
$dependencyChecker = Join-Path $PSScriptRoot "check_dense_ws_runtime_dependencies.ps1"
if (-not $PolicyPath) {
    $PolicyPath = Join-Path $projectRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
}
$testPlanPath = $PlanPath
$testExpectedPlanHash = $ExpectedPlanHash
$testPolicyPath = $PolicyPath

. $gateway

$PlanPath = $testPlanPath
$ExpectedPlanHash = $testExpectedPlanHash
$PolicyPath = $testPolicyPath

function Copy-JsonObject {
    param([Parameter(Mandatory = $true)]$Value)
    return $Value | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100 -DateKind String
}

function Invoke-FreshGuard {
    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $guardScript -Json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Guard failed: $($raw | Out-String)"
    }
    return ($raw | Out-String) | ConvertFrom-Json -DateKind String
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$PolicyPath = [System.IO.Path]::GetFullPath($PolicyPath)
$frozenLauncher = [System.IO.Path]::GetFullPath($frozenLauncher)
$policy = Get-Content -Raw -LiteralPath $PolicyPath | ConvertFrom-Json -DateKind String
$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json -DateKind String
$guard = Invoke-FreshGuard
$receiptPath = [System.IO.Path]::GetFullPath(
    [string]$policy.next_long_campaign.user_launch_approval.receipt_path
)
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json -DateKind String

$common = @{
    PolicyFileSha256 = Get-Sha256 -Path $PolicyPath
    PlanPath = $PlanPath
    PlanFileSha256 = Get-Sha256 -Path $PlanPath
    ExpectedPlanHash = $ExpectedPlanHash
    ReceiptPath = $receiptPath
    ReceiptFileSha256 = Get-Sha256 -Path $receiptPath
    FrozenLauncherPath = $frozenLauncher
    FrozenLauncherSha256 = Get-Sha256 -Path $frozenLauncher
}

$passed = 0
$failed = 0
$cases = [System.Collections.Generic.List[object]]::new()

function Record-Pass {
    param([string]$Name)
    $script:passed++
    $script:cases.Add([ordered]@{ name = $Name; passed = $true })
}

function Record-Fail {
    param([string]$Name, [string]$Reason)
    $script:failed++
    $script:cases.Add([ordered]@{ name = $Name; passed = $false; reason = $Reason })
}

function Expect-Rejection {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Policy,
        [Parameter(Mandatory = $true)]$Guard,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)]$Receipt,
        [hashtable]$Overrides = @{}
    )
    $arguments = @{}
    foreach ($entry in $common.GetEnumerator()) {
        $arguments[$entry.Key] = $entry.Value
    }
    foreach ($entry in $Overrides.GetEnumerator()) {
        $arguments[$entry.Key] = $entry.Value
    }
    $arguments.Policy = $Policy
    $arguments.Guard = $Guard
    $arguments.Plan = $Plan
    $arguments.Receipt = $Receipt
    try {
        Assert-DenseWsExactLaunchApproval @arguments | Out-Null
        Record-Fail -Name $Name -Reason "validator accepted tampered input"
    } catch {
        Record-Pass -Name $Name
    }
}

try {
    Assert-DenseWsExactLaunchApproval `
        -Policy $policy -Guard $guard -Plan $plan -Receipt $receipt @common |
        Out-Null
    Record-Pass -Name "accept_exact_current_binding"
} catch {
    Record-Fail -Name "accept_exact_current_binding" -Reason $_.Exception.Message
}

$tampered = Copy-JsonObject $receipt
$tampered.status = "REJECTED"
Expect-Rejection "reject_receipt_status" $policy $guard $plan $tampered

$tampered = Copy-JsonObject $receipt
$tampered.plan_hash = "0" * 64
Expect-Rejection "reject_receipt_plan_hash" $policy $guard $plan $tampered

$tampered = Copy-JsonObject $receipt
$tampered.stop_incomplete_recovery_authorized = $true
Expect-Rejection "reject_recovery_permission" $policy $guard $plan $tampered

$tampered = Copy-JsonObject $receipt
$tampered.max_runtime_sec = [long]$tampered.max_runtime_sec + 1
Expect-Rejection "reject_runtime_change" $policy $guard $plan $tampered

$tampered = Copy-JsonObject $guard
$tampered.long_campaign_approval.status = "MISSING"
Expect-Rejection "reject_guard_without_approval" $policy $tampered $plan $receipt

$tampered = Copy-JsonObject $policy
$tampered.next_long_campaign.user_launch_approval.receipt_sha256 = "0" * 64
Expect-Rejection "reject_policy_receipt_hash" $tampered $guard $plan $receipt

$tampered = Copy-JsonObject $plan
$tampered.launch_controls.tools.launcher.sha256 = "0" * 64
Expect-Rejection "reject_plan_launcher_hash" $policy $guard $tampered $receipt

Expect-Rejection `
    -Name "reject_current_launcher_hash" `
    -Policy $policy -Guard $guard -Plan $plan -Receipt $receipt `
    -Overrides @{ FrozenLauncherSha256 = "0" * 64 }

try {
    $dependencyRaw = & pwsh -NoProfile -ExecutionPolicy Bypass `
        -File $dependencyChecker `
        -PlanPath $PlanPath `
        -ExpectedPlanHash $ExpectedPlanHash `
        -Json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "dependency checker failed: $($dependencyRaw | Out-String)"
    }
    $dependency = ($dependencyRaw | Out-String) |
        ConvertFrom-Json -Depth 100 -DateKind String
    if (
        $dependency.status -eq "READY" -and
        $dependency.no_run_or_output_writes -eq $true -and
        $dependency.network_request_performed -eq $false -and
        $dependency.writer_started -eq $false
    ) {
        Record-Pass -Name "accept_exact_runtime_dependencies"
    } else {
        Record-Fail `
            -Name "accept_exact_runtime_dependencies" `
            -Reason "dependency readiness is not exact READY"
    }
} catch {
    Record-Fail `
        -Name "accept_exact_runtime_dependencies" `
        -Reason $_.Exception.Message
}

try {
    $gatewayRaw = & pwsh -NoProfile -ExecutionPolicy Bypass `
        -File $gateway `
        -PlanPath $PlanPath `
        -ExpectedPlanHash $ExpectedPlanHash `
        -PolicyPath $PolicyPath `
        -PreflightOnly `
        -Json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gateway preflight failed: $($gatewayRaw | Out-String)"
    }
    $gatewayResult = ($gatewayRaw | Out-String) |
        ConvertFrom-Json -Depth 100 -DateKind String
    if (
        $gatewayResult.status -eq "EXACT_APPROVAL_VALIDATED_PREFLIGHT_ONLY" -and
        $gatewayResult.no_run_or_output_writes -eq $true -and
        $gatewayResult.runtime_dependency_readiness.status -eq "READY"
    ) {
        Record-Pass -Name "gateway_preflight_requires_runtime_readiness"
    } else {
        Record-Fail `
            -Name "gateway_preflight_requires_runtime_readiness" `
            -Reason "gateway did not surface exact runtime readiness"
    }
} catch {
    Record-Fail `
        -Name "gateway_preflight_requires_runtime_readiness" `
        -Reason $_.Exception.Message
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_launch_approval_gateway_test_v1"
    passed = $failed -eq 0
    passed_count = $passed
    failed_count = $failed
    cases = $cases
    market_rows_read = $false
    network_collector_started = $false
    evaluator_started = $false
    returns_read = $false
    pnl_read = $false
    oos_run = $false
    grid_or_retune = $false
}
$result | ConvertTo-Json -Depth 12
if ($failed -ne 0) {
    exit 1
}
