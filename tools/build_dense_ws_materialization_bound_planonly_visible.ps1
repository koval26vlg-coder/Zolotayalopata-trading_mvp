[CmdletBinding()]
param(
    [string]$PolicyPath = "",
    [ValidateRange(60, 1800)][int]$MaxRuntimeSec = 1800,
    [switch]$PreflightOnly,
    [switch]$Json,
    [switch]$VisibleChild,
    [string]$ReservationPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GuardChecker = Join-Path $ProjectRoot "tools\check_trading_mvp_autopilot.ps1"
if (-not $PolicyPath) {
    $PolicyPath = Join-Path $ProjectRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
}

function Resolve-TradingMvpPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime is unavailable. Set TRADING_MVP_PYTHON."
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
    try {
        [System.IO.File]::WriteAllText(
            $temporary,
            (($Payload | ConvertTo-Json -Depth 32) + [Environment]::NewLine),
            [System.Text.UTF8Encoding]::new($false)
        )
        [System.IO.File]::Move($temporary, $Path, $true)
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Write-JsonCreateNew {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    $parent = Split-Path -Parent $Path
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(
        (($Payload | ConvertTo-Json -Depth 32) + [Environment]::NewLine)
    )
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read
        )
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        if ($stream) {
            $stream.Dispose()
        }
    }
}

function Get-Guard {
    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GuardChecker -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Authoritative trading MVP guard failed."
    }
    return (@($raw) -join [Environment]::NewLine) | ConvertFrom-Json
}

function Assert-HashBoundFile {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "$Label expected SHA-256 is invalid."
    }
    if ((Get-Sha256 -Path $Path) -ne $ExpectedSha256) {
        throw "$Label file hash mismatch."
    }
}

function Test-ProcessAlive {
    param($ProcessId)
    try {
        if ($null -eq $ProcessId) {
            return $false
        }
        Get-Process -Id ([int]$ProcessId) -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Write-VisibleLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "[$([DateTimeOffset]::Now.ToString('o'))] $Message"
    Write-Host $line
    [System.IO.File]::AppendAllText(
        $script:VisibleLogPath,
        $line + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Invoke-BoundedBuilder {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][DateTimeOffset]$Deadline
    )
    foreach ($path in @($script:StdoutPath, $script:StderrPath)) {
        if (Test-Path -LiteralPath $path) {
            throw "Refusing to overwrite builder log: $path"
        }
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $script:Python
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Failed to start the materialization-bound PlanOnly builder."
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    Write-VisibleLog "PlanOnly hash binding started pid=$($process.Id)"
    try {
        while (-not $process.HasExited) {
            if ([DateTimeOffset]::Now -ge $Deadline) {
                try { $process.Kill($true) } catch {}
                $process.WaitForExit()
                throw "PlanOnly hash binding exceeded MaxRuntimeSec."
            }
            $elapsed = [math]::Round(
                ([DateTimeOffset]::Now - $script:StartedAt).TotalSeconds,
                1
            )
            Write-VisibleLog "PlanOnly hash binding running elapsed_sec=$elapsed"
            Start-Sleep -Seconds 5
        }
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        [System.IO.File]::WriteAllText(
            $script:StdoutPath,
            $stdout,
            [System.Text.UTF8Encoding]::new($false)
        )
        [System.IO.File]::WriteAllText(
            $script:StderrPath,
            $stderr,
            [System.Text.UTF8Encoding]::new($false)
        )
        if ($stdout) { Write-Host $stdout }
        if ($stderr) { Write-Host $stderr -ForegroundColor Yellow }
        if ($process.ExitCode -ne 0) {
            throw "PlanOnly builder exited with code $($process.ExitCode)."
        }
    } finally {
        $process.Dispose()
    }
}

$PolicyPath = [System.IO.Path]::GetFullPath($PolicyPath)
foreach ($required in @($PolicyPath, $GuardChecker, $PSCommandPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file is missing: $required"
    }
}

$Policy = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json
$Config = $Policy.dense_ws_materialization_bound_planonly
$Candidate = $Policy.next_long_campaign
$Freeze = $Policy.dense_ws_signal_evaluator_freeze
$Postrun = $Policy.dense_ws_postrun
if (
    [string]$Config.status -ne "READY_CONTRACT_FREEZE_ONLY" -or
    $Config.automatic_same_hash_planonly_build_authorized -ne $true -or
    $Config.evaluation_authorized -ne $false -or
    $Config.returns_pnl_oos_allowed -ne $false -or
    $Config.network_collector_allowed -ne $false -or
    $Config.grid_or_retune_allowed -ne $false -or
    $Config.paper_live_private_api_real_capital_leverage_margin_allowed -ne $false
) {
    throw "Materialization-bound PlanOnly policy is not safely frozen."
}
if ($MaxRuntimeSec -ne [int]$Config.max_runtime_sec) {
    throw "MaxRuntimeSec must exactly match the frozen policy."
}

$BuilderPath = [System.IO.Path]::GetFullPath([string]$Config.builder_path)
$WrapperPath = [System.IO.Path]::GetFullPath([string]$Config.visible_wrapper_path)
if ($WrapperPath -ne [System.IO.Path]::GetFullPath($PSCommandPath)) {
    throw "Visible wrapper path does not match the frozen policy."
}
Assert-HashBoundFile -Label "PlanOnly builder" -Path $BuilderPath `
    -ExpectedSha256 ([string]$Config.builder_sha256)
Assert-HashBoundFile -Label "Visible wrapper" -Path $WrapperPath `
    -ExpectedSha256 ([string]$Config.visible_wrapper_sha256)

$ProposalPath = [System.IO.Path]::GetFullPath([string]$Freeze.proposal_path)
$FreezeReceiptPath = [System.IO.Path]::GetFullPath([string]$Freeze.approval_receipt_path)
$FrozenContractPath = [System.IO.Path]::GetFullPath([string]$Freeze.contract_path)
$FrozenPlanPath = [System.IO.Path]::GetFullPath([string]$Freeze.plan_path)
$CampaignContractPath = [System.IO.Path]::GetFullPath([string]$Candidate.contract_path)
$CampaignPlanPath = [System.IO.Path]::GetFullPath([string]$Candidate.plan_path)
Assert-HashBoundFile -Label "Proposal" -Path $ProposalPath `
    -ExpectedSha256 ([string]$Freeze.proposal_file_sha256)
Assert-HashBoundFile -Label "Freeze approval" -Path $FreezeReceiptPath `
    -ExpectedSha256 ([string]$Freeze.approval_receipt_sha256)
Assert-HashBoundFile -Label "Frozen contract" -Path $FrozenContractPath `
    -ExpectedSha256 ([string]$Freeze.contract_file_sha256)
Assert-HashBoundFile -Label "Frozen PlanOnly" -Path $FrozenPlanPath `
    -ExpectedSha256 ([string]$Freeze.plan_file_sha256)
Assert-HashBoundFile -Label "Campaign contract" -Path $CampaignContractPath `
    -ExpectedSha256 ([string]$Candidate.contract_file_sha256)
Assert-HashBoundFile -Label "Campaign PlanOnly" -Path $CampaignPlanPath `
    -ExpectedSha256 ([string]$Candidate.plan_file_sha256)

$CampaignPlan = Get-Content -LiteralPath $CampaignPlanPath -Raw | ConvertFrom-Json
if (
    [string]$CampaignPlan.campaign_id -ne [string]$Candidate.campaign_id -or
    [string]$CampaignPlan.plan_hash -ne [string]$Candidate.plan_hash -or
    [string]$Freeze.status -ne "FROZEN_NOT_AUTHORIZED" -or
    $Freeze.evaluation_authorized -ne $false -or
    $Freeze.returns_pnl_oos_allowed -ne $false
) {
    throw "Campaign or frozen signal/evaluator identity mismatch."
}
$CampaignRoot = [System.IO.Path]::GetFullPath(
    [string]$CampaignPlan.outputs.campaign_root
)
$PostrunRoot = [System.IO.Path]::GetFullPath((Join-Path $CampaignRoot "_postrun"))
$QualityPath = Join-Path $PostrunRoot ([string]$Postrun.output_names.quality_report)
$MaterializationPath = Join-Path $PostrunRoot ([string]$Postrun.output_names.materialization_manifest)
$OutputPath = Join-Path $PostrunRoot ([string]$Config.output_name)
$OwnerPath = Join-Path $PostrunRoot ([string]$Config.owner_name)
$ReservationDefaultPath = "$OwnerPath.reservation.json"
$script:VisibleLogPath = Join-Path $PostrunRoot "materialization-bound-planonly.visible.log"
$script:StdoutPath = Join-Path $PostrunRoot "materialization-bound-planonly.stdout.log"
$script:StderrPath = Join-Path $PostrunRoot "materialization-bound-planonly.stderr.log"

$Guard = Get-Guard
$Disposition = $Guard.dense_ws_postrun_disposition
$preflightStatus = "NOT_READY"
$preflightReasons = [System.Collections.Generic.List[string]]::new()
if ([string]$Guard.status -ne "ACTIVE" -or $Guard.stop_new_actions -eq $true) {
    $preflightReasons.Add("guard_not_active")
}
if (
    [string]$Disposition.campaign_id -ne [string]$Candidate.campaign_id -or
    [string]$Disposition.plan_hash -ne [string]$Candidate.plan_hash
) {
    $preflightReasons.Add("postrun_disposition_identity_mismatch")
}
switch ([string]$Disposition.status) {
    "MATERIALIZATION_ACCEPTED" { $preflightStatus = "READY" }
    "MATERIALIZATION_BOUND_PLAN_RUNNING" { $preflightStatus = "ALREADY_RUNNING" }
    "MATERIALIZATION_BOUND_PLANONLY_READY" { $preflightStatus = "COMPLETE" }
    "STOPPED_INCOMPLETE" { $preflightStatus = "STOPPED_INCOMPLETE" }
    "INTEGRITY_CONFLICT" { $preflightStatus = "INTEGRITY_CONFLICT" }
    default { $preflightReasons.Add("accepted_materialization_not_ready") }
}
if (-not (Test-Path -LiteralPath $QualityPath -PathType Leaf)) {
    $preflightReasons.Add("quality_report_missing")
}
if (-not (Test-Path -LiteralPath $MaterializationPath -PathType Leaf)) {
    $preflightReasons.Add("materialization_manifest_missing")
}
if (Test-Path -LiteralPath $ReservationDefaultPath -PathType Leaf) {
    $reservation = Get-Content -LiteralPath $ReservationDefaultPath -Raw | ConvertFrom-Json
    $isThisVisibleChild = (
        $VisibleChild -and
        [int]$reservation.terminal_pid -eq $PID
    )
    if ($isThisVisibleChild) {
        # The top-level launcher reserved this exact run for this visible terminal.
    } elseif (Test-ProcessAlive -ProcessId $reservation.terminal_pid) {
        $preflightStatus = "ALREADY_RUNNING"
    } else {
        $preflightStatus = "STOPPED_INCOMPLETE"
        $preflightReasons.Add("stale_reservation_requires_review")
    }
}
if ($preflightReasons.Count -gt 0 -and $preflightStatus -eq "READY") {
    $preflightStatus = "NOT_READY"
}
$preflight = [ordered]@{
    schema = "trading_mvp_dense_ws_materialization_bound_planonly_preflight_v1"
    status = $preflightStatus
    campaign_id = [string]$Candidate.campaign_id
    campaign_plan_hash = [string]$Candidate.plan_hash
    frozen_plan_hash = [string]$Freeze.plan_hash
    reasons = @($preflightReasons)
    max_runtime_sec = $MaxRuntimeSec
    output_path = $OutputPath
    owner_path = $OwnerPath
    evaluation_authorized = $false
    returns_pnl_oos_allowed = $false
    no_run_or_output_writes = [bool]$PreflightOnly
}
if ($PreflightOnly) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 16 } else { $preflight | Format-List }
    exit 0
}
if ($preflightStatus -ne "READY") {
    throw "Materialization-bound PlanOnly is not launchable: status=$preflightStatus reasons=$(@($preflightReasons) -join ',')."
}

if ($VisibleChild) {
    if (-not $ReservationPath) {
        throw "VisibleChild requires ReservationPath."
    }
    $ReservationPath = [System.IO.Path]::GetFullPath($ReservationPath)
    if ($ReservationPath -ne [System.IO.Path]::GetFullPath($ReservationDefaultPath)) {
        throw "VisibleChild reservation path mismatch."
    }
    $reservation = $null
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-Path -LiteralPath $ReservationPath -PathType Leaf) {
            try {
                $candidateReservation = Get-Content -LiteralPath $ReservationPath -Raw | ConvertFrom-Json
                if ([int]$candidateReservation.terminal_pid -eq $PID) {
                    $reservation = $candidateReservation
                    break
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $reservation) {
        throw "VisibleChild did not receive its parent-bound reservation."
    }
    $script:StartedAt = [DateTimeOffset]::Now
    $owner = [ordered]@{
        schema = "trading_mvp_dense_ws_materialization_bound_plan_owner_v1"
        campaign_id = [string]$Candidate.campaign_id
        campaign_plan_hash = [string]$Candidate.plan_hash
        frozen_plan_hash = [string]$Freeze.plan_hash
        terminal_pid = $PID
        started_at = $script:StartedAt.ToString('o')
        max_runtime_sec = $MaxRuntimeSec
        output_path = $OutputPath
        status = "RUNNING"
        final = $false
        evaluation_authorized = $false
        returns_pnl_oos_allowed = $false
    }
    Write-JsonCreateNew -Path $OwnerPath -Payload $owner
    Remove-Item -LiteralPath $ReservationPath -Force
    try {
        $script:Python = Resolve-TradingMvpPython
        $deadline = $script:StartedAt.AddSeconds($MaxRuntimeSec)
        $arguments = @(
            $BuilderPath,
            "--proposal", $ProposalPath,
            "--freeze-approval-receipt", $FreezeReceiptPath,
            "--frozen-contract", $FrozenContractPath,
            "--frozen-plan", $FrozenPlanPath,
            "--campaign-contract", $CampaignContractPath,
            "--campaign-plan", $CampaignPlanPath,
            "--quality", $QualityPath,
            "--materialization", $MaterializationPath,
            "--output", $OutputPath,
            "--max-runtime-sec", [string]$MaxRuntimeSec
        )
        Invoke-BoundedBuilder -Arguments $arguments -Deadline $deadline
        if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
            throw "Builder exited successfully but immutable PlanOnly is missing."
        }
        $boundPlan = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
        if (
            $boundPlan.executable -ne $false -or
            $boundPlan.authorization.evaluation_authorized -ne $false -or
            $boundPlan.authorization.returns_pnl_oos_allowed -ne $false -or
            [string]$boundPlan.next_allowed_action -ne "REQUEST_EXACT_HASH_BOUND_EVALUATOR_APPROVAL"
        ) {
            throw "Created PlanOnly violates the no-evaluator boundary."
        }
        $owner.status = "COMPLETE"
        $owner.final = $true
        $owner.finished_at = [DateTimeOffset]::Now.ToString('o')
        $owner.output_sha256 = Get-Sha256 -Path $OutputPath
        $owner.bound_plan_hash = [string]$boundPlan.plan_hash
        Write-JsonAtomic -Path $OwnerPath -Payload $owner
        Write-VisibleLog "PlanOnly created. Evaluator remains forbidden pending exact approval."
        exit 0
    } catch {
        $owner.status = "STOPPED_INCOMPLETE"
        $owner.final = $true
        $owner.finished_at = [DateTimeOffset]::Now.ToString('o')
        $owner.error = $_.Exception.Message
        Write-JsonAtomic -Path $OwnerPath -Payload $owner
        Write-Host $_.Exception.Message -ForegroundColor Red
        throw
    }
}

$reservation = [ordered]@{
    schema = "trading_mvp_dense_ws_materialization_bound_plan_reservation_v1"
    campaign_id = [string]$Candidate.campaign_id
    campaign_plan_hash = [string]$Candidate.plan_hash
    frozen_plan_hash = [string]$Freeze.plan_hash
    parent_pid = $PID
    terminal_pid = $null
    created_at = [DateTimeOffset]::Now.ToString('o')
    nonce = [Guid]::NewGuid().ToString('N')
}
Write-JsonCreateNew -Path $ReservationDefaultPath -Payload $reservation
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$childArguments = @(
    "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass",
    "-File", $PSCommandPath,
    "-PolicyPath", $PolicyPath,
    "-MaxRuntimeSec", [string]$MaxRuntimeSec,
    "-VisibleChild",
    "-ReservationPath", $ReservationDefaultPath
)
try {
    $terminal = Start-Process -FilePath $pwsh -ArgumentList $childArguments `
        -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
    $reservation.terminal_pid = $terminal.Id
    Write-JsonAtomic -Path $ReservationDefaultPath -Payload $reservation
} catch {
    Remove-Item -LiteralPath $ReservationDefaultPath -Force -ErrorAction SilentlyContinue
    throw
}

$ownershipVerified = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    if (Test-Path -LiteralPath $OwnerPath -PathType Leaf) {
        try {
            $claimed = Get-Content -LiteralPath $OwnerPath -Raw | ConvertFrom-Json
            if (
                [int]$claimed.terminal_pid -eq $terminal.Id -and
                [string]$claimed.campaign_id -eq [string]$Candidate.campaign_id -and
                [string]$claimed.campaign_plan_hash -eq [string]$Candidate.plan_hash
            ) {
                $ownershipVerified = $true
                break
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 250
}
if (-not $ownershipVerified) {
    throw "Visible terminal launched but PlanOnly ownership was not verified. Do not retry automatically."
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_materialization_bound_plan_visible_launch_v1"
    status = "VISIBLE_TERMINAL_LAUNCHED"
    campaign_id = [string]$Candidate.campaign_id
    run_id = "$([string]$Candidate.campaign_id)_materialization_bound_planonly"
    campaign_plan_hash = [string]$Candidate.plan_hash
    frozen_plan_hash = [string]$Freeze.plan_hash
    terminal_pid = $terminal.Id
    terminal_ownership_verified = $true
    output_path = $OutputPath
    owner_path = $OwnerPath
    max_runtime_sec = $MaxRuntimeSec
    evaluation_authorized = $false
    returns_pnl_oos_allowed = $false
}
if ($Json) { $result | ConvertTo-Json -Depth 16 } else { $result | Format-List }
