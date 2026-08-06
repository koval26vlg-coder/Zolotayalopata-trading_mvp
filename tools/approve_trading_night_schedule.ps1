param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [string]$GatePath = "",
    [string]$ApprovalRecordRoot = "",
    [switch]$ConfirmedNightScheduleApproval,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$validator = Join-Path $repoRoot "trading_mvp\src\night_schedule_plan.py"
if (-not $GatePath) {
    $GatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
}
if (-not $ApprovalRecordRoot) {
    $ApprovalRecordRoot = Join-Path $repoRoot "docs\agent-log\night-schedule-approvals"
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

if (-not $ConfirmedNightScheduleApproval) {
    throw "-ConfirmedNightScheduleApproval is required. The PlanOnly schedule itself is not permission to collect."
}
if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "Night schedule plan not found: $PlanPath"
}
if (-not (Test-Path -LiteralPath $GatePath)) {
    throw "Active run gate not found: $GatePath"
}

$gate = ConvertFrom-JsonPreserveDateStrings -InputJson (Get-Content -LiteralPath $GatePath -Raw)
if ([string]$gate.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Schedule approval cannot change an active run."
}
if ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resolve the incomplete run before approving a schedule."
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
$firstSegment = @($plan.segments)[0]
$stageAuthorizationJson = & $python $validator authorize-segment `
    --plan $PlanPath `
    --expected-plan-hash $ExpectedPlanHash `
    --run-id ([string]$firstSegment.run_id)
if ($LASTEXITCODE -ne 0) {
    throw "Night schedule collection-stage authorization failed with exit code $LASTEXITCODE"
}
$stageAuthorization = ConvertFrom-JsonPreserveDateStrings -InputJson $stageAuthorizationJson
if ([string]$stageAuthorization.verdict -ne "AUTHORIZED") {
    throw "Night schedule collection-stage authorization did not return AUTHORIZED"
}
$lastSegment = @($plan.segments)[-1]
$expiresAt = ConvertTo-DateTimeOffsetInvariant -Value ([string]$lastSegment.hard_deadline_local)
if ($expiresAt -le [DateTimeOffset]::Now) {
    throw "Night schedule has already expired: $($expiresAt.ToString('o'))"
}

$approvalRecordPath = Join-Path $ApprovalRecordRoot "$ExpectedPlanHash.approval.json"
if (Test-Path -LiteralPath $approvalRecordPath) {
    throw "Refusing to overwrite immutable night schedule approval: $approvalRecordPath"
}
$approvedAt = [DateTimeOffset]::Now
$approval = [ordered]@{
    schema = "trading_mvp_night_schedule_approval_v1"
    status = "ACTIVE"
    approved_at = $approvedAt.ToString("o")
    expires_at = $expiresAt.ToString("o")
    approved_by = "User"
    approval_scope = "one frozen collection-stage schedule; no auto-resume; no OOS evaluation/grid/paper/live/API keys"
    plan_path = [System.IO.Path]::GetFullPath($PlanPath)
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    data_type = [string]$plan.hypothesis.required_data_type
    collection_stage = [string]$stageAuthorization.collection_stage
    quality_ledger_path = [string]$stageAuthorization.quality_ledger_path
    accepted_distinct_dates_at_approval = [int]$stageAuthorization.accepted_distinct_dates_before_run
    stage_target_distinct_dates = [int]$stageAuthorization.stage_target_distinct_dates
    segment_run_ids = @($plan.segments | ForEach-Object { [string]$_.run_id })
    visible_terminal_required = $true
    data_embargo = $true
    auto_resume_allowed = $false
}
Write-JsonAtomic -Object $approval -Path $approvalRecordPath
$approvalRecordSha256 = (Get-FileHash -LiteralPath $approvalRecordPath -Algorithm SHA256).Hash.ToLowerInvariant()

Set-JsonProperty -Object $gate -Name "updated_at" -Value $approvedAt.ToString("o")
Set-JsonProperty -Object $gate -Name "next_goal_decision" -Value "PIT_UNIVERSE_V2_NIGHT_SCHEDULE_APPROVED"
Set-JsonProperty -Object $gate -Name "next_goal_reason" -Value "One immutable PIT_UNIVERSE_V2_FORWARD schedule was explicitly approved; only its hash-bound visible segments may start in their approved windows."
Set-JsonProperty -Object $gate -Name "next_step_after_ready" -Value "Run only the next due hash-bound visible PIT segment; no OOS evaluation/grid/probe/paper/live/API keys and no auto-resume."
Set-JsonProperty -Object $gate -Name "replay_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "grid_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "paper_forward_allowed" -Value $false
Set-JsonProperty -Object $gate -Name "requires_explicit_user_approval_for_actual_collect" -Value $false
Set-JsonProperty -Object $gate -Name "approved_night_schedule" -Value ([ordered]@{
    status = "ACTIVE"
    plan_path = [System.IO.Path]::GetFullPath($PlanPath)
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    approval_record_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
    approval_record_sha256 = $approvalRecordSha256
    approved_at = $approvedAt.ToString("o")
    expires_at = $expiresAt.ToString("o")
    data_embargo = $true
    auto_resume_allowed = $false
    collection_stage = [string]$stageAuthorization.collection_stage
    quality_ledger_path = [string]$stageAuthorization.quality_ledger_path
})
Write-JsonAtomic -Object $gate -Path $GatePath

$result = [ordered]@{
    schema = "trading_mvp_night_schedule_approval_result_v1"
    decision = "NIGHT_SCHEDULE_APPROVED"
    plan_path = [System.IO.Path]::GetFullPath($PlanPath)
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = [string]$validation.plan_file_sha256
    approval_record_path = [System.IO.Path]::GetFullPath($approvalRecordPath)
    approval_record_sha256 = $approvalRecordSha256
    gate_path = [System.IO.Path]::GetFullPath($GatePath)
    expires_at = $expiresAt.ToString("o")
    collection_stage = [string]$stageAuthorization.collection_stage
    quality_ledger_path = [string]$stageAuthorization.quality_ledger_path
    collection_started = $false
    next_allowed_action = "wait_for_next_approved_visible_segment_window"
}
if ($Json) {
    $result | ConvertTo-Json -Depth 12
} else {
    Write-Host "Night schedule approved; no collector started." -ForegroundColor Cyan
    Write-Host "Plan hash: $ExpectedPlanHash"
    Write-Host "Approval: $approvalRecordPath"
    Write-Host "Expires: $($expiresAt.ToString('o'))"
}
