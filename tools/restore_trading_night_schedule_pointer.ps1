param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$ApprovalRecordPath = "",
    [string]$GatePath = "",
    [string]$OutputPath = "",
    [switch]$ConfirmedPointerRestore,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$validator = Join-Path $repoRoot "trading_mvp\src\night_schedule_plan.py"
if (-not $GatePath) {
    $GatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
}
if (-not $ApprovalRecordPath) {
    $ApprovalRecordPath = Join-Path $repoRoot "docs\agent-log\night-schedule-approvals\$ExpectedPlanHash.approval.json"
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
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

function Get-NormalizedExistingPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path).TrimEnd('\', '/')
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

if (-not $ConfirmedPointerRestore) {
    throw "-ConfirmedPointerRestore is required. This tool restores only an existing immutable user approval."
}
foreach ($requiredPath in @($PlanPath, $ApprovalRecordPath, $GatePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath"
    }
}
if ($OutputPath -and (Test-Path -LiteralPath $OutputPath)) {
    throw "Refusing to overwrite restore audit output: $OutputPath"
}

$gateSha256Before = (Get-FileHash -LiteralPath $GatePath -Algorithm SHA256).Hash.ToLowerInvariant()
$approvalSha256Before = (Get-FileHash -LiteralPath $ApprovalRecordPath -Algorithm SHA256).Hash.ToLowerInvariant()
$gate = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $GatePath -Raw)
$gateStates = @([string]$gate.status, [string]$gate.gate_status) | Where-Object { $_ }
if ($gateStates -contains "RUNNING") {
    throw "Active run gate is RUNNING. Approval pointer restore is not allowed."
}
if ($gateStates -contains "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resolve the incomplete run before pointer restore."
}

$python = Resolve-Python
$validationJson = & $python $validator validate --plan $PlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) {
    throw "Night schedule validation failed with exit code $LASTEXITCODE"
}
$validation = ConvertFrom-JsonPreserveDateStrings -InputJson $validationJson
if ([string]$validation.verdict -ne "VALID") {
    throw "Night schedule validation did not return VALID"
}
$plan = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $PlanPath -Raw)
$segments = @($plan.segments | Where-Object { [string]$_.run_id -eq $RunId })
if ($segments.Count -ne 1) {
    throw "Schedule must contain exactly one requested run_id: $RunId"
}
$segment = $segments[0]

$authorizationJson = & $python $validator authorize-segment `
    --plan $PlanPath `
    --expected-plan-hash $ExpectedPlanHash `
    --run-id $RunId
if ($LASTEXITCODE -ne 0) {
    throw "Night schedule collection-stage authorization failed with exit code $LASTEXITCODE"
}
$authorization = ConvertFrom-JsonPreserveDateStrings -InputJson $authorizationJson
if ([string]$authorization.verdict -ne "AUTHORIZED") {
    throw "Night schedule collection-stage authorization did not return AUTHORIZED"
}

$approval = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $ApprovalRecordPath -Raw)
$approvalErrors = [System.Collections.Generic.List[string]]::new()
if ([string]$approval.schema -ne "trading_mvp_night_schedule_approval_v1") {
    $approvalErrors.Add("unexpected approval schema")
}
if ([string]$approval.status -ne "ACTIVE") {
    $approvalErrors.Add("approval status is not ACTIVE")
}
if ([string]$approval.approved_by -ne "User") {
    $approvalErrors.Add("approval was not recorded as user-approved")
}
if ([string]$approval.plan_hash -ne $ExpectedPlanHash) {
    $approvalErrors.Add("approval plan_hash mismatch")
}
if (-not (Test-PathsEqual -Left ([string]$approval.plan_path) -Right (Get-NormalizedExistingPath -Path $PlanPath))) {
    $approvalErrors.Add("approval plan_path mismatch")
}
if ([string]$approval.plan_file_sha256 -ne [string]$validation.plan_file_sha256) {
    $approvalErrors.Add("approval plan_file_sha256 mismatch")
}
if ([string]$approval.data_type -ne [string]$plan.hypothesis.required_data_type) {
    $approvalErrors.Add("approval data_type mismatch")
}
if ([string]$approval.collection_stage -ne [string]$authorization.collection_stage) {
    $approvalErrors.Add("approval collection_stage mismatch")
}
if (-not (Test-PathsEqual -Left ([string]$approval.quality_ledger_path) -Right ([string]$authorization.quality_ledger_path))) {
    $approvalErrors.Add("approval quality_ledger_path mismatch")
}
if (-not (@($approval.segment_run_ids) -contains $RunId)) {
    $approvalErrors.Add("immutable approval does not authorize run_id $RunId")
}
if ($approval.visible_terminal_required -ne $true) {
    $approvalErrors.Add("approval does not require a visible terminal")
}
if ($approval.data_embargo -ne $true) {
    $approvalErrors.Add("approval does not preserve the data embargo")
}
if ($approval.auto_resume_allowed -ne $false) {
    $approvalErrors.Add("approval unexpectedly allows auto-resume")
}

try {
    $expiresAt = ConvertTo-DateTimeOffsetInvariant -Value ([string]$approval.expires_at)
    $segmentDeadline = ConvertTo-DateTimeOffsetInvariant -Value ([string]$segment.hard_deadline_local)
    if ($expiresAt -le [DateTimeOffset]::Now) {
        $approvalErrors.Add("immutable approval has expired")
    }
    if ($segmentDeadline -gt $expiresAt) {
        $approvalErrors.Add("requested segment is outside approval expiry")
    }
} catch {
    $approvalErrors.Add("approval or segment deadline is invalid: $($_.Exception.Message)")
}

if ($approvalErrors.Count -gt 0) {
    throw "Immutable approval validation failed: $($approvalErrors -join '; ')"
}

if ((Get-FileHash -LiteralPath $ApprovalRecordPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $approvalSha256Before) {
    throw "Immutable approval changed during validation. Refusing pointer restore."
}
if ((Get-FileHash -LiteralPath $GatePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $gateSha256Before) {
    throw "Active run gate changed during validation. Refusing pointer restore."
}

$restoredAt = [DateTimeOffset]::Now
$previousPlanHash = if ($gate.approved_night_schedule) {
    [string]$gate.approved_night_schedule.plan_hash
} else {
    $null
}
$approvalRecordFullPath = Get-NormalizedExistingPath -Path $ApprovalRecordPath
$planFullPath = Get-NormalizedExistingPath -Path $PlanPath

Set-JsonProperty -Object $gate -Name "updated_at" -Value $restoredAt.ToString("o")
Set-JsonProperty -Object $gate -Name "next_goal_decision" -Value "PIT_UNIVERSE_V2_NIGHT_SCHEDULE_POINTER_RESTORED"
Set-JsonProperty -Object $gate -Name "next_goal_reason" -Value "Restored an existing immutable user-approved schedule after a completed supplemental run replaced only the active gate pointer."
Set-JsonProperty -Object $gate -Name "next_step_after_ready" -Value "Wait for approved run_id $RunId; launch it only in its visible sealed window after the normal gate and authorization checks."
Set-JsonProperty -Object $gate -Name "replay_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "grid_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "paper_forward_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "requires_explicit_user_approval_for_actual_collect" -Value $false
Set-JsonProperty -Object $gate -Name "approved_night_schedule" -Value ([ordered]@{
    status = "ACTIVE"
    plan_path = $planFullPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    approval_record_path = $approvalRecordFullPath
    approval_record_sha256 = $approvalSha256Before
    approved_at = [string]$approval.approved_at
    expires_at = [string]$approval.expires_at
    data_embargo = $true
    auto_resume_allowed = $false
    collection_stage = [string]$authorization.collection_stage
    quality_ledger_path = [string]$authorization.quality_ledger_path
})
Write-JsonAtomic -Object $gate -Path $GatePath

$result = [ordered]@{
    schema = "trading_mvp_night_schedule_pointer_restore_v1"
    decision = "NIGHT_SCHEDULE_POINTER_RESTORED"
    restored_at = $restoredAt.ToString("o")
    gate_path = [System.IO.Path]::GetFullPath($GatePath)
    previous_plan_hash = $previousPlanHash
    restored_plan_path = $planFullPath
    restored_plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    approval_record_path = $approvalRecordFullPath
    approval_record_sha256 = $approvalSha256Before
    approval_record_unchanged = $true
    run_id = $RunId
    collection_stage = [string]$authorization.collection_stage
    accepted_distinct_dates_before_run = [int]$authorization.accepted_distinct_dates_before_run
    remaining_stage_dates_before_run = [int]$authorization.remaining_stage_dates_before_run
    collection_started = $false
    network_access = $false
    returns_read = $false
    pnl_read = $false
    next_allowed_action = "wait_for_approved_visible_segment_window"
}
if ($OutputPath) {
    Write-JsonAtomic -Object $result -Path $OutputPath
}
if ($Json) {
    $result | ConvertTo-Json -Depth 16
} else {
    Write-Host "Night schedule pointer restored from immutable approval; no collector started." -ForegroundColor Cyan
    Write-Host "Plan hash: $ExpectedPlanHash"
    Write-Host "Run id: $RunId"
}
