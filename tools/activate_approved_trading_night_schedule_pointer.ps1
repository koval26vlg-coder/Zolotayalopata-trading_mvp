param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [string]$GatePath = "",
    [string]$ApprovalRecordRoot = "",
    [string]$SchedulePointerPath = "",
    [string]$GlobalWriterClaimPath = "",
    [switch]$ConfirmedNightScheduleActivation,
    [switch]$PreflightOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$validator = Join-Path $repoRoot "trading_mvp\src\night_schedule_plan.py"
$approvalScript = Join-Path $repoRoot "tools\approve_trading_night_schedule.ps1"
if (-not $GatePath) {
    $GatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
}
if (-not $ApprovalRecordRoot) {
    $ApprovalRecordRoot = Join-Path $repoRoot "docs\agent-log\night-schedule-approvals"
}
if (-not $SchedulePointerPath) {
    $SchedulePointerPath = Join-Path $repoRoot "docs\agent-log\trading-mvp-autopilot-schedule-pointer.json"
}
if (-not $GlobalWriterClaimPath) {
    $GlobalWriterClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    $resolved = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($resolved) { return $resolved }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $jsonText = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $jsonText | ConvertFrom-Json -DateKind String
    }
    return $jsonText | ConvertFrom-Json
}

function ConvertTo-DateTimeOffsetInvariant {
    param([Parameter(Mandatory = $true)][string]$Value)

    return [DateTimeOffset]::Parse(
        $Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-PathsEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return [System.StringComparer]::OrdinalIgnoreCase.Equals(
        [System.IO.Path]::GetFullPath($Left).TrimEnd('\', '/'),
        [System.IO.Path]::GetFullPath($Right).TrimEnd('\', '/')
    )
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
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Test-StringArrayExact {
    param(
        [Parameter(Mandatory = $true)]$Left,
        [Parameter(Mandatory = $true)]$Right
    )

    $leftItems = @($Left | ForEach-Object { [string]$_ })
    $rightItems = @($Right | ForEach-Object { [string]$_ })
    if ($leftItems.Count -ne $rightItems.Count) { return $false }
    for ($index = 0; $index -lt $leftItems.Count; $index++) {
        if ($leftItems[$index] -cne $rightItems[$index]) { return $false }
    }
    return $true
}

function Assert-ApprovalRecord {
    param(
        [Parameter(Mandatory = $true)]$Approval,
        [Parameter(Mandatory = $true)][string]$ApprovalPath,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][string]$FullPlanPath,
        [Parameter(Mandatory = $true)][string]$PlanHash,
        [Parameter(Mandatory = $true)][string]$PlanFileSha256,
        [Parameter(Mandatory = $true)]$Authorization,
        [Parameter(Mandatory = $true)][DateTimeOffset]$FinalDeadline
    )

    $errors = [System.Collections.Generic.List[string]]::new()
    $expectedRunIds = @($Plan.segments | ForEach-Object { [string]$_.run_id })
    if ([string]$Approval.schema -ne "trading_mvp_night_schedule_approval_v1") {
        $errors.Add("schema mismatch")
    }
    if ([string]$Approval.status -ne "ACTIVE") {
        $errors.Add("status is not ACTIVE")
    }
    if ([string]$Approval.approved_by -ne "User") {
        $errors.Add("approved_by mismatch")
    }
    if ([string]$Approval.approval_scope -ne "one frozen collection-stage schedule; no auto-resume; no OOS evaluation/grid/paper/live/API keys") {
        $errors.Add("approval_scope mismatch")
    }
    if ([string]$Approval.plan_hash -ne $PlanHash) {
        $errors.Add("plan_hash mismatch")
    }
    try {
        if (-not (Test-PathsEqual -Left ([string]$Approval.plan_path) -Right $FullPlanPath)) {
            $errors.Add("plan_path mismatch")
        }
    } catch {
        $errors.Add("plan_path invalid")
    }
    if ([string]$Approval.plan_file_sha256 -ne $PlanFileSha256) {
        $errors.Add("plan_file_sha256 mismatch")
    }
    if ([string]$Approval.data_type -ne [string]$Plan.hypothesis.required_data_type) {
        $errors.Add("data_type mismatch")
    }
    if ([string]$Approval.collection_stage -ne [string]$Authorization.collection_stage) {
        $errors.Add("collection_stage mismatch")
    }
    try {
        if (-not (Test-PathsEqual -Left ([string]$Approval.quality_ledger_path) -Right ([string]$Authorization.quality_ledger_path))) {
            $errors.Add("quality_ledger_path mismatch")
        }
    } catch {
        $errors.Add("quality_ledger_path invalid")
    }
    if (-not (Test-StringArrayExact -Left @($Approval.segment_run_ids) -Right $expectedRunIds)) {
        $errors.Add("segment_run_ids mismatch")
    }
    if ([int]$Approval.accepted_distinct_dates_at_approval -ne [int]$Authorization.accepted_distinct_dates_before_run) {
        $errors.Add("accepted_distinct_dates_at_approval mismatch")
    }
    if ([int]$Approval.stage_target_distinct_dates -ne [int]$Authorization.stage_target_distinct_dates) {
        $errors.Add("stage_target_distinct_dates mismatch")
    }
    if ($Approval.visible_terminal_required -ne $true) {
        $errors.Add("visible_terminal_required is not true")
    }
    if ($Approval.data_embargo -ne $true) {
        $errors.Add("data_embargo is not true")
    }
    if ($Approval.auto_resume_allowed -ne $false) {
        $errors.Add("auto_resume_allowed is not false")
    }
    try {
        $approvedAt = ConvertTo-DateTimeOffsetInvariant -Value ([string]$Approval.approved_at)
        $expiresAt = ConvertTo-DateTimeOffsetInvariant -Value ([string]$Approval.expires_at)
        if ($approvedAt -gt [DateTimeOffset]::Now) {
            $errors.Add("approved_at is in the future")
        }
        if ($expiresAt -le [DateTimeOffset]::Now) {
            $errors.Add("approval has expired")
        }
        if ($expiresAt -ne $FinalDeadline) {
            $errors.Add("expires_at does not equal the final segment deadline")
        }
        if ($approvedAt -ge $expiresAt) {
            $errors.Add("approved_at is not before expires_at")
        }
    } catch {
        $errors.Add("approved_at or expires_at invalid")
    }
    if ($errors.Count -gt 0) {
        throw "Immutable approval validation failed for $ApprovalPath`: $($errors -join '; ')"
    }
}

function Test-GateBinding {
    param(
        [Parameter(Mandatory = $true)]$Gate,
        [Parameter(Mandatory = $true)][string]$FullPlanPath,
        [Parameter(Mandatory = $true)][string]$PlanHash,
        [Parameter(Mandatory = $true)][string]$PlanFileSha256,
        [Parameter(Mandatory = $true)][string]$ApprovalPath,
        [Parameter(Mandatory = $true)][string]$ApprovalSha256,
        [Parameter(Mandatory = $true)]$Approval,
        [Parameter(Mandatory = $true)]$Authorization
    )

    $binding = $Gate.approved_night_schedule
    if (-not $binding) { return $false }
    try {
        return (
            [string]$binding.status -eq "ACTIVE" -and
            (Test-PathsEqual -Left ([string]$binding.plan_path) -Right $FullPlanPath) -and
            [string]$binding.plan_hash -eq $PlanHash -and
            [string]$binding.plan_file_sha256 -eq $PlanFileSha256 -and
            (Test-PathsEqual -Left ([string]$binding.approval_record_path) -Right $ApprovalPath) -and
            [string]$binding.approval_record_sha256 -eq $ApprovalSha256 -and
            [string]$binding.approved_at -eq [string]$Approval.approved_at -and
            [string]$binding.expires_at -eq [string]$Approval.expires_at -and
            $binding.data_embargo -eq $true -and
            $binding.auto_resume_allowed -eq $false -and
            [string]$binding.collection_stage -eq [string]$Authorization.collection_stage -and
            (Test-PathsEqual -Left ([string]$binding.quality_ledger_path) -Right ([string]$Authorization.quality_ledger_path))
        )
    } catch {
        return $false
    }
}

function Test-PointerBinding {
    param(
        $Pointer,
        [Parameter(Mandatory = $true)][string]$FullPlanPath,
        [Parameter(Mandatory = $true)][string]$PlanHash,
        [Parameter(Mandatory = $true)][string]$PlanFileSha256,
        [Parameter(Mandatory = $true)][string]$ApprovalPath,
        [Parameter(Mandatory = $true)][string]$ApprovalSha256,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)]$Authorization
    )

    if (-not $Pointer) { return $false }
    try {
        return (
            [string]$Pointer.schema -eq "trading_mvp_autopilot_schedule_pointer_v1" -and
            [string]$Pointer.status -eq "ACTIVE" -and
            [string]$Pointer.project -eq "trading_mvp" -and
            [string]$Pointer.hypothesis_id -eq [string]$Plan.hypothesis.id -and
            [string]$Pointer.data_type -eq [string]$Plan.hypothesis.required_data_type -and
            [string]$Pointer.collection_stage -eq [string]$Authorization.collection_stage -and
            (Test-PathsEqual -Left ([string]$Pointer.plan_path) -Right $FullPlanPath) -and
            [string]$Pointer.plan_hash -eq $PlanHash -and
            [string]$Pointer.plan_file_sha256 -eq $PlanFileSha256 -and
            (Test-PathsEqual -Left ([string]$Pointer.approval_path) -Right $ApprovalPath) -and
            [string]$Pointer.approval_sha256 -eq $ApprovalSha256 -and
            (Test-PathsEqual -Left ([string]$Pointer.quality_ledger_path) -Right ([string]$Authorization.quality_ledger_path))
        )
    } catch {
        return $false
    }
}

function Assert-UnchangedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowNull()][string]$ExpectedSha256
    )

    if ($ExpectedSha256) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Concurrent change detected: file disappeared: $Path"
        }
        if ((Get-FileSha256 -Path $Path) -ne $ExpectedSha256) {
            throw "Concurrent change detected: file hash changed: $Path"
        }
    } elseif (Test-Path -LiteralPath $Path) {
        throw "Concurrent change detected: path appeared: $Path"
    }
}

if ($PreflightOnly -and $ConfirmedNightScheduleActivation) {
    throw "PreflightOnly and ConfirmedNightScheduleActivation are mutually exclusive."
}
if (-not $PreflightOnly -and -not $ConfirmedNightScheduleActivation) {
    throw "-ConfirmedNightScheduleActivation is required. PlanOnly and preflight do not authorize schedule activation."
}
foreach ($requiredPath in @($PlanPath, $GatePath, $validator, $approvalScript)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

$fullPlanPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PlanPath).Path)
$fullGatePath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $GatePath).Path)
$fullApprovalRoot = [System.IO.Path]::GetFullPath($ApprovalRecordRoot)
$fullPointerPath = [System.IO.Path]::GetFullPath($SchedulePointerPath)
$fullWriterClaimPath = [System.IO.Path]::GetFullPath($GlobalWriterClaimPath)
$approvalRecordPath = Join-Path $fullApprovalRoot "$ExpectedPlanHash.approval.json"
$gateSha256Before = Get-FileSha256 -Path $fullGatePath
$pointerSha256Before = if (Test-Path -LiteralPath $fullPointerPath -PathType Leaf) {
    Get-FileSha256 -Path $fullPointerPath
} else {
    $null
}

$gate = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullGatePath -Raw)
$gateStates = @([string]$gate.status, [string]$gate.gate_status) | Where-Object { $_ }
if ($gateStates -contains "RUNNING") {
    throw "Active run gate is RUNNING. Schedule activation is not allowed."
}
if ($gateStates -contains "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resolve it before schedule activation."
}
if (Test-Path -LiteralPath $fullWriterClaimPath) {
    throw "Global market writer claim exists. Schedule activation is not allowed: $fullWriterClaimPath"
}

$python = Resolve-Python
$validationJson = & $python $validator validate --plan $fullPlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) {
    throw "Night schedule validation failed with exit code $LASTEXITCODE"
}
$validation = ConvertFrom-JsonPreserveDateStrings -InputJson $validationJson
if ([string]$validation.verdict -ne "VALID") {
    throw "Night schedule validation did not return VALID"
}
$plan = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullPlanPath -Raw)
$segments = @($plan.segments)
if ($segments.Count -lt 1) {
    throw "Night schedule has no segments."
}
$firstSegment = $segments[0]
$lastSegment = $segments[-1]
$authorizationJson = & $python $validator authorize-segment `
    --plan $fullPlanPath `
    --expected-plan-hash $ExpectedPlanHash `
    --run-id ([string]$firstSegment.run_id)
if ($LASTEXITCODE -ne 0) {
    throw "Night schedule collection-stage authorization failed with exit code $LASTEXITCODE"
}
$authorization = ConvertFrom-JsonPreserveDateStrings -InputJson $authorizationJson
if ([string]$authorization.verdict -ne "AUTHORIZED") {
    throw "Night schedule collection-stage authorization did not return AUTHORIZED"
}
$finalDeadline = ConvertTo-DateTimeOffsetInvariant -Value ([string]$lastSegment.hard_deadline_local)
if ($finalDeadline -le [DateTimeOffset]::Now) {
    throw "Night schedule has already expired: $($finalDeadline.ToString('o'))"
}

$approvalExistsAtStart = Test-Path -LiteralPath $approvalRecordPath -PathType Leaf
$approvalSha256Before = if ($approvalExistsAtStart) {
    Get-FileSha256 -Path $approvalRecordPath
} else {
    $null
}
$approval = $null
$approvalSha256 = $approvalSha256Before
if ($approvalExistsAtStart) {
    $approval = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $approvalRecordPath -Raw)
    Assert-ApprovalRecord `
        -Approval $approval `
        -ApprovalPath $approvalRecordPath `
        -Plan $plan `
        -FullPlanPath $fullPlanPath `
        -PlanHash $ExpectedPlanHash `
        -PlanFileSha256 ([string]$validation.plan_file_sha256) `
        -Authorization $authorization `
        -FinalDeadline $finalDeadline
}

$pointer = if (Test-Path -LiteralPath $fullPointerPath -PathType Leaf) {
    ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullPointerPath -Raw)
} else {
    $null
}
$gateBound = $false
$pointerBound = $false
if ($approval) {
    $gateBound = Test-GateBinding `
        -Gate $gate `
        -FullPlanPath $fullPlanPath `
        -PlanHash $ExpectedPlanHash `
        -PlanFileSha256 ([string]$validation.plan_file_sha256) `
        -ApprovalPath $approvalRecordPath `
        -ApprovalSha256 $approvalSha256 `
        -Approval $approval `
        -Authorization $authorization
    $pointerBound = Test-PointerBinding `
        -Pointer $pointer `
        -FullPlanPath $fullPlanPath `
        -PlanHash $ExpectedPlanHash `
        -PlanFileSha256 ([string]$validation.plan_file_sha256) `
        -ApprovalPath $approvalRecordPath `
        -ApprovalSha256 $approvalSha256 `
        -Plan $plan `
        -Authorization $authorization
}

if ($PreflightOnly) {
    $preflightDecision = if (-not $approvalExistsAtStart) {
        "READY_TO_CREATE_APPROVAL_AND_ACTIVATE"
    } elseif ($gateBound -and $pointerBound) {
        "NIGHT_SCHEDULE_POINTER_ALREADY_ACTIVE"
    } else {
        "READY_TO_RECOVER_EXISTING_APPROVAL"
    }
    $preflight = [ordered]@{
        schema = "trading_mvp_night_schedule_pointer_activation_preflight_v1"
        decision = $preflightDecision
        checks_passed = $true
        plan_path = $fullPlanPath
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = [string]$validation.plan_file_sha256
        approval_record_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
        approval_exists = $approvalExistsAtStart
        approval_valid = [bool]$approval
        gate_bound = $gateBound
        pointer_path = $fullPointerPath
        pointer_bound = $pointerBound
        global_writer_claim_path = $fullWriterClaimPath
        global_writer_claim_absent = $true
        first_run_id = [string]$firstSegment.run_id
        expires_at = $finalDeadline.ToString("o")
        collection_stage = [string]$authorization.collection_stage
        collection_started = $false
        network_access = $false
        side_effects = "NONE"
    }
    if ($Json) {
        $preflight | ConvertTo-Json -Depth 16
    } else {
        Write-Host "Night schedule activation preflight passed; no files changed." -ForegroundColor Cyan
        Write-Host "Decision: $preflightDecision"
        Write-Host "Plan hash: $ExpectedPlanHash"
    }
    exit 0
}

if ($approval -and $gateBound -and $pointerBound) {
    $alreadyActive = [ordered]@{
        schema = "trading_mvp_night_schedule_pointer_activation_v1"
        decision = "NIGHT_SCHEDULE_POINTER_ALREADY_ACTIVE"
        plan_path = $fullPlanPath
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = [string]$validation.plan_file_sha256
        approval_record_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
        approval_record_sha256 = $approvalSha256
        gate_path = $fullGatePath
        pointer_path = $fullPointerPath
        approval_created = $false
        gate_updated = $false
        pointer_written = $false
        partial_activation_recovered = $false
        collection_started = $false
        network_access = $false
        next_allowed_action = "wait_for_next_approved_visible_segment_window"
    }
    if ($Json) {
        $alreadyActive | ConvertTo-Json -Depth 16
    } else {
        Write-Host "Night schedule pointer is already active; no files changed." -ForegroundColor Cyan
        Write-Host "Plan hash: $ExpectedPlanHash"
    }
    exit 0
}

Assert-UnchangedPath -Path $fullGatePath -ExpectedSha256 $gateSha256Before
Assert-UnchangedPath -Path $fullPointerPath -ExpectedSha256 $pointerSha256Before
if ($approvalExistsAtStart) {
    Assert-UnchangedPath -Path $approvalRecordPath -ExpectedSha256 $approvalSha256Before
}

$approvalCreated = $false
if (-not $approvalExistsAtStart) {
    $approvalArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $approvalScript,
        "-PlanPath", $fullPlanPath,
        "-ExpectedPlanHash", $ExpectedPlanHash,
        "-GatePath", $fullGatePath,
        "-ApprovalRecordRoot", $fullApprovalRoot,
        "-ConfirmedNightScheduleApproval", "-Json"
    )
    $previousPython = $env:TRADING_MVP_PYTHON
    try {
        $env:TRADING_MVP_PYTHON = $python
        $approvalOutput = & pwsh @approvalArgs
        $approvalExitCode = $LASTEXITCODE
    } finally {
        $env:TRADING_MVP_PYTHON = $previousPython
    }
    if ($approvalExitCode -ne 0) {
        throw "Sealed night schedule approval failed with exit code $approvalExitCode"
    }
    $approvalResult = ConvertFrom-JsonPreserveDateStrings -InputJson $approvalOutput
    if ([string]$approvalResult.decision -ne "NIGHT_SCHEDULE_APPROVED") {
        throw "Sealed night schedule approval did not return NIGHT_SCHEDULE_APPROVED"
    }
    if (-not (Test-Path -LiteralPath $approvalRecordPath -PathType Leaf)) {
        throw "Sealed approval did not create the expected immutable receipt: $approvalRecordPath"
    }
    if (-not (Test-PathsEqual -Left ([string]$approvalResult.approval_record_path) -Right $approvalRecordPath)) {
        throw "Sealed approval returned an unexpected receipt path."
    }
    $approvalCreated = $true
}

$approvalSha256 = Get-FileSha256 -Path $approvalRecordPath
$approval = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $approvalRecordPath -Raw)
Assert-ApprovalRecord `
    -Approval $approval `
    -ApprovalPath $approvalRecordPath `
    -Plan $plan `
    -FullPlanPath $fullPlanPath `
    -PlanHash $ExpectedPlanHash `
    -PlanFileSha256 ([string]$validation.plan_file_sha256) `
    -Authorization $authorization `
    -FinalDeadline $finalDeadline

$gate = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullGatePath -Raw)
$gateStates = @([string]$gate.status, [string]$gate.gate_status) | Where-Object { $_ }
if ($gateStates -contains "RUNNING" -or $gateStates -contains "STOPPED_INCOMPLETE") {
    throw "Active run gate changed to a non-activatable state after approval."
}
$gateBound = Test-GateBinding `
    -Gate $gate `
    -FullPlanPath $fullPlanPath `
    -PlanHash $ExpectedPlanHash `
    -PlanFileSha256 ([string]$validation.plan_file_sha256) `
    -ApprovalPath $approvalRecordPath `
    -ApprovalSha256 $approvalSha256 `
    -Approval $approval `
    -Authorization $authorization

$activatedAt = [DateTimeOffset]::Now
$gateUpdated = $false
if (-not $gateBound) {
    if (-not $approvalCreated) {
        Assert-UnchangedPath -Path $fullGatePath -ExpectedSha256 $gateSha256Before
    }
    Set-JsonProperty -Object $gate -Name "updated_at" -Value $activatedAt.ToString("o")
    Set-JsonProperty -Object $gate -Name "next_goal_decision" -Value "PIT_UNIVERSE_V2_NIGHT_SCHEDULE_APPROVED"
    Set-JsonProperty -Object $gate -Name "next_goal_reason" -Value "One immutable PIT_UNIVERSE_V2_FORWARD schedule was explicitly approved; only its hash-bound visible segments may start in their approved windows."
    Set-JsonProperty -Object $gate -Name "next_step_after_ready" -Value "Run only the next due hash-bound visible PIT segment; no OOS evaluation/grid/probe/paper/live/API keys and no auto-resume."
    Set-JsonProperty -Object $gate -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gate -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gate -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gate -Name "requires_explicit_user_approval_for_actual_collect" -Value $false
    Set-JsonProperty -Object $gate -Name "approved_night_schedule" -Value ([ordered]@{
        status = "ACTIVE"
        plan_path = $fullPlanPath
        plan_hash = $ExpectedPlanHash
        plan_file_sha256 = [string]$validation.plan_file_sha256
        approval_record_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
        approval_record_sha256 = $approvalSha256
        approved_at = [string]$approval.approved_at
        expires_at = [string]$approval.expires_at
        data_embargo = $true
        auto_resume_allowed = $false
        collection_stage = [string]$authorization.collection_stage
        quality_ledger_path = [string]$authorization.quality_ledger_path
    })
    Write-JsonAtomic -Object $gate -Path $fullGatePath
    $gateUpdated = $true
}

Assert-UnchangedPath -Path $approvalRecordPath -ExpectedSha256 $approvalSha256
$gateAfter = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullGatePath -Raw)
if (-not (Test-GateBinding `
    -Gate $gateAfter `
    -FullPlanPath $fullPlanPath `
    -PlanHash $ExpectedPlanHash `
    -PlanFileSha256 ([string]$validation.plan_file_sha256) `
    -ApprovalPath $approvalRecordPath `
    -ApprovalSha256 $approvalSha256 `
    -Approval $approval `
    -Authorization $authorization)) {
    throw "Active run gate does not contain the exact approval binding. Dynamic pointer was not changed."
}
$gateSha256ForPointer = Get-FileSha256 -Path $fullGatePath

Assert-UnchangedPath -Path $fullPointerPath -ExpectedSha256 $pointerSha256Before
Assert-UnchangedPath -Path $fullGatePath -ExpectedSha256 $gateSha256ForPointer
if (Test-Path -LiteralPath $fullWriterClaimPath) {
    throw "Global market writer claim appeared during activation. Dynamic pointer was not changed: $fullWriterClaimPath"
}
$pointerPayload = [ordered]@{
    schema = "trading_mvp_autopilot_schedule_pointer_v1"
    status = "ACTIVE"
    project = "trading_mvp"
    hypothesis_id = [string]$plan.hypothesis.id
    data_type = [string]$plan.hypothesis.required_data_type
    collection_stage = [string]$authorization.collection_stage
    plan_path = $fullPlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    approval_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
    approval_sha256 = $approvalSha256
    quality_ledger_path = [System.IO.Path]::GetFullPath([string]$authorization.quality_ledger_path)
    train_target_distinct_dates = [int]$authorization.stage_target_distinct_dates
    updated_at = $activatedAt.ToString("o")
}
Write-JsonAtomic -Object $pointerPayload -Path $fullPointerPath

$pointerAfter = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $fullPointerPath -Raw)
if (-not (Test-PointerBinding `
    -Pointer $pointerAfter `
    -FullPlanPath $fullPlanPath `
    -PlanHash $ExpectedPlanHash `
    -PlanFileSha256 ([string]$validation.plan_file_sha256) `
    -ApprovalPath $approvalRecordPath `
    -ApprovalSha256 $approvalSha256 `
    -Plan $plan `
    -Authorization $authorization)) {
    throw "Dynamic PIT schedule pointer readback validation failed."
}

$result = [ordered]@{
    schema = "trading_mvp_night_schedule_pointer_activation_v1"
    decision = "NIGHT_SCHEDULE_POINTER_ACTIVATED"
    activated_at = $activatedAt.ToString("o")
    plan_path = $fullPlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    approval_record_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
    approval_record_sha256 = $approvalSha256
    gate_path = $fullGatePath
    pointer_path = $fullPointerPath
    pointer_sha256 = Get-FileSha256 -Path $fullPointerPath
    approval_created = $approvalCreated
    gate_updated = $gateUpdated
    pointer_written = $true
    partial_activation_recovered = [bool](-not $approvalCreated -and (-not $gateBound -or -not $pointerBound))
    first_run_id = [string]$firstSegment.run_id
    expires_at = [string]$approval.expires_at
    collection_stage = [string]$authorization.collection_stage
    collection_started = $false
    network_access = $false
    returns_read = $false
    pnl_read = $false
    next_allowed_action = "wait_for_next_approved_visible_segment_window"
}
if ($Json) {
    $result | ConvertTo-Json -Depth 16
} else {
    Write-Host "Night schedule approval and dynamic pointer are active; no collector started." -ForegroundColor Cyan
    Write-Host "Plan hash: $ExpectedPlanHash"
    Write-Host "First run: $($firstSegment.run_id)"
    Write-Host "Pointer: $fullPointerPath"
}
