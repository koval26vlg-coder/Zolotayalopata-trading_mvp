param(
    [string]$ThreadId = "019e738a-b37c-7a33-ae04-6cc80739f184",
    [double]$MinWeeklyRemainingPercent = 15.0,
    [int]$UsageStaleAfterSec = 108000,
    [string]$PolicyPath = "",
    [string]$GatePath = "",
    [string]$StatePath = "",
    [string]$CurrentReadinessPointerPath = "",
    [string]$GlobalWriterClaimPath = "",
    [string]$SessionRoot = "",
    [string]$PitPostrunSummaryPath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$guard = Join-Path $repoRoot "trading_mvp\src\autopilot_guard.py"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
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

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $temporaryPath = "$Path.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
    try {
        [System.IO.File]::WriteAllText(
            $temporaryPath,
            $Text + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

$python = Resolve-Python
if (-not $PolicyPath) {
    $PolicyPath = Join-Path $repoRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
}
if (-not $GatePath) {
    $GatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
}
if (-not $StatePath) {
    $StatePath = Join-Path $repoRoot "docs\agent-log\trading-mvp-autopilot-state.json"
}
if (-not $SessionRoot) {
    $SessionRoot = Join-Path $env:USERPROFILE ".codex\sessions"
}
if (-not $CurrentReadinessPointerPath) {
    $CurrentReadinessPointerPath = Join-Path `
        $repoRoot `
        "docs\agent-log\one-week-edge-sprint-readiness-pointer.json"
}
if (-not $GlobalWriterClaimPath) {
    $GlobalWriterClaimPath = Join-Path `
        $repoRoot `
        "docs\agent-log\active-market-data-writer-claim.json"
}

foreach ($requiredPath in @(
    $guard,
    $PolicyPath,
    $GatePath,
    $SessionRoot
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required autopilot input is missing: $requiredPath"
    }
}
if ($MinWeeklyRemainingPercent -le 0 -or $MinWeeklyRemainingPercent -ge 100) {
    throw "MinWeeklyRemainingPercent must be in (0, 100)."
}
if ($UsageStaleAfterSec -lt 60) {
    throw "UsageStaleAfterSec must be >= 60."
}

$priorState = if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -LiteralPath $StatePath -Raw
    )
} else {
    $null
}

$output = & $python $guard `
    --policy $PolicyPath `
    --gate $GatePath `
    --state $StatePath `
    --current-readiness-pointer $CurrentReadinessPointerPath `
    --global-writer-claim $GlobalWriterClaimPath `
    --session-root $SessionRoot `
    --thread-id $ThreadId `
    --min-remaining-percent $MinWeeklyRemainingPercent `
    --stale-after-sec $UsageStaleAfterSec

if ($LASTEXITCODE -ne 0) {
    throw "Autopilot guard failed with exit code $LASTEXITCODE."
}

$text = @($output) -join [Environment]::NewLine
$state = ConvertFrom-JsonPreserveDateStrings -InputJson $text
$postrunChecker = Join-Path $repoRoot "tools\check_trading_mvp_pit_postrun_summary.ps1"
if (-not (Test-Path -LiteralPath $postrunChecker -PathType Leaf)) {
    throw "PIT postrun summary checker is missing: $postrunChecker"
}

$guardSnapshotPath = (
    "$StatePath.pit-postrun-input.$PID.$([Guid]::NewGuid().ToString('N')).json"
)
try {
    Write-JsonAtomic -Path $guardSnapshotPath -Text $text
    $pwshPath = (Get-Process -Id $PID -ErrorAction Stop).Path
    $checkerArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $postrunChecker,
        "-GuardStatePath", $guardSnapshotPath,
        "-Json"
    )
    if ($PitPostrunSummaryPath) {
        $checkerArguments += @("-SummaryPath", $PitPostrunSummaryPath)
    }
    $postrunOutput = & $pwshPath @checkerArguments
    $postrunExitCode = $LASTEXITCODE
    $postrunText = @($postrunOutput) -join [Environment]::NewLine
    $postrunDisposition = ConvertFrom-JsonPreserveDateStrings -InputJson $postrunText
} finally {
    if (Test-Path -LiteralPath $guardSnapshotPath) {
        Remove-Item -LiteralPath $guardSnapshotPath -Force
    }
}

$allowedPostrunStatuses = @(
    "NOT_APPLICABLE",
    "MISSING",
    "DEFERRED",
    "COMPLETE",
    "RECOVERY_REQUIRED",
    "INTEGRITY_CONFLICT"
)
if (
    [string]$postrunDisposition.schema -ne
        "trading_mvp_pit_postrun_summary_disposition_v1" -or
    [string]$postrunDisposition.status -notin $allowedPostrunStatuses -or
    $postrunDisposition.market_rows_read -ne $false -or
    $postrunDisposition.returns_read -ne $false -or
    $postrunDisposition.pnl_read -ne $false -or
    $postrunDisposition.oos_run -ne $false
) {
    throw "PIT postrun summary checker returned an invalid disposition."
}
if (
    ($postrunExitCode -eq 0) -ne
    ([string]$postrunDisposition.status -ne "INTEGRITY_CONFLICT")
) {
    throw (
        "PIT postrun summary checker exit/status mismatch: " +
        "exit=$postrunExitCode status=$($postrunDisposition.status)"
    )
}

$notificationRequired = $false
$postrunRequiresNotification = (
    [string]$postrunDisposition.status -in @(
        "RECOVERY_REQUIRED",
        "INTEGRITY_CONFLICT"
    )
)
if ($postrunRequiresNotification) {
    $priorDisposition = $priorState.pit_postrun_disposition
    $notificationRequired = -not (
        [string]$priorDisposition.status -eq
            [string]$postrunDisposition.status -and
        [string]$priorDisposition.run_id -eq [string]$postrunDisposition.run_id -and
        [string]$priorDisposition.schedule_plan_hash -eq
            [string]$postrunDisposition.schedule_plan_hash -and
        [string]$priorDisposition.reason -eq [string]$postrunDisposition.reason
    )
}
$postrunDisposition |
    Add-Member `
        -NotePropertyName "notification_required" `
        -NotePropertyValue $notificationRequired `
        -Force
$state |
    Add-Member `
        -NotePropertyName "pit_postrun_disposition" `
        -NotePropertyValue $postrunDisposition `
        -Force

if ([string]$postrunDisposition.status -eq "INTEGRITY_CONFLICT") {
    $state.status = "CRITICAL_STOP"
    $state.decision = "CRITICAL_STOP_PIT_POSTRUN_INTEGRITY_CONFLICT"
    $state.stop_new_actions = $true
    $state.action_due = $notificationRequired
    $state.critical_checkpoint_notification_required = $notificationRequired
    $state.next_action = "notify_pit_postrun_integrity_conflict"
} elseif ([string]$postrunDisposition.status -eq "RECOVERY_REQUIRED") {
    $state.decision = "USER_REVIEW_REQUIRED_PIT_POSTRUN_RECOVERY"
    $state.action_due = $notificationRequired
    $state.critical_checkpoint_notification_required = $notificationRequired
    $state.next_action = "request_exact_pit_postrun_reconciliation_approval"
}

$text = $state | ConvertTo-Json -Depth 32
Write-JsonAtomic -Path $StatePath -Text $text
if ($Json) {
    $text
    exit 0
}

Write-Host "[autopilot] status=$($state.status) decision=$($state.decision)" -ForegroundColor Cyan
Write-Host "[autopilot] weekly_used=$($state.usage.used_percent)% weekly_remaining=$($state.usage.remaining_percent)% threshold=$($state.usage.min_remaining_percent)%"
Write-Host "[autopilot] weekly_reset=$($state.usage.resets_at_local)"
Write-Host "[autopilot] gate=$($state.gate.status) run_id=$($state.gate.run_id)"
Write-Host "[autopilot] next=$($state.next_action)"
if ($state.productive_fallback) {
    Write-Host "[autopilot] fallback=$($state.productive_fallback.status) task=$($state.productive_fallback.task.id)"
}
if ($state.research_fallback) {
    Write-Host "[autopilot] research=$($state.research_fallback.status) task=$($state.research_fallback.task.id)"
}
Write-Host (
    "[autopilot] pit_postrun=$($state.pit_postrun_disposition.status) " +
    "run_id=$($state.pit_postrun_disposition.run_id)"
)
Write-Host "[autopilot] state=$StatePath"
