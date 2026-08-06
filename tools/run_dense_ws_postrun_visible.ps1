[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPlanHash,
    [string]$PolicyPath = "",
    [ValidateRange(60, 3600)][int]$TotalMaxRuntimeSec = 3600,
    [ValidateRange(60, 1800)][int]$QualityMaxRuntimeSec = 1800,
    [ValidateRange(60, 1800)][int]$MaterializationMaxRuntimeSec = 1800,
    [switch]$PreflightOnly,
    [switch]$Json,
    [switch]$VisibleChild,
    [string]$ReservationPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GuardChecker = Join-Path $ProjectRoot "tools\check_trading_mvp_autopilot.ps1"
$QualityModule = Join-Path $ProjectRoot "trading_mvp\src\dense_ws_campaign_quality.py"
$MaterializerModule = Join-Path $ProjectRoot "trading_mvp\src\dense_ws_causal_materializer.py"
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

function Get-EarliestDeadline {
    param([Parameter(Mandatory = $true)][DateTimeOffset[]]$Candidates)
    if ($Candidates.Count -lt 1) {
        throw "At least one deadline candidate is required."
    }
    $earliest = $Candidates[0]
    foreach ($candidate in $Candidates) {
        if ($candidate -lt $earliest) {
            $earliest = $candidate
        }
    }
    return $earliest
}

function ConvertFrom-IsoDateTimeOffset {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [DateTimeOffset]::ParseExact(
        $Value,
        "yyyy-MM-dd'T'HH:mm:sszzz",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None
    )
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
        $text = ($Payload | ConvertTo-Json -Depth 24) + [Environment]::NewLine
        [System.IO.File]::WriteAllText(
            $temporary,
            $text,
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
        (($Payload | ConvertTo-Json -Depth 24) + [Environment]::NewLine)
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

function Get-Guard {
    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GuardChecker -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Authoritative trading MVP guard failed."
    }
    return (@($raw) -join [Environment]::NewLine) | ConvertFrom-Json -DateKind String
}

function Get-OutputPath {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)]$Names,
        [Parameter(Mandatory = $true)][string]$PostrunRoot
    )
    $name = [string]$Names.$Key
    if (-not $name -or [System.IO.Path]::GetFileName($name) -ne $name) {
        throw "Invalid dense_ws_postrun output name: $Key"
    }
    return [System.IO.Path]::GetFullPath((Join-Path $PostrunRoot $name))
}

function Invoke-BoundedPython {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][DateTimeOffset]$Deadline
    )
    $stdoutPath = Join-Path $script:PostrunRoot "$Stage.stdout.log"
    $stderrPath = Join-Path $script:PostrunRoot "$Stage.stderr.log"
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) {
            throw "Refusing to overwrite stage log: $path"
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
        throw "Failed to start $Stage."
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    Write-VisibleLog "$Stage started pid=$($process.Id)"
    try {
        while (-not $process.HasExited) {
            if ([DateTimeOffset]::Now -ge $Deadline) {
                try {
                    $process.Kill($true)
                } catch {}
                $process.WaitForExit()
                throw "$Stage exceeded its bounded stage or total deadline."
            }
            $elapsed = [math]::Round(
                ([DateTimeOffset]::Now - $script:StartedAt).TotalSeconds,
                1
            )
            Write-VisibleLog "$Stage running elapsed_sec=$elapsed"
            Start-Sleep -Seconds 5
        }
        $process.WaitForExit()
        if ([DateTimeOffset]::Now -gt $Deadline) {
            throw "$Stage completed after its bounded stage or total deadline."
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        [System.IO.File]::WriteAllText(
            $stdoutPath,
            $stdout,
            [System.Text.UTF8Encoding]::new($false)
        )
        [System.IO.File]::WriteAllText(
            $stderrPath,
            $stderr,
            [System.Text.UTF8Encoding]::new($false)
        )
        if ($stdout) {
            Write-Host $stdout
        }
        if ($stderr) {
            Write-Host $stderr -ForegroundColor Yellow
        }
        if ($process.ExitCode -ne 0) {
            throw "$Stage exited with code $($process.ExitCode)."
        }
        Write-VisibleLog "$Stage completed exit_code=0"
    } finally {
        $process.Dispose()
    }
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$PolicyPath = [System.IO.Path]::GetFullPath($PolicyPath)
$ExpectedPlanHash = $ExpectedPlanHash.ToLowerInvariant()
foreach ($required in @(
    $PlanPath,
    $PolicyPath,
    $GuardChecker,
    $QualityModule,
    $MaterializerModule,
    $PSCommandPath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file is missing: $required"
    }
}

$Policy = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json -DateKind String
$Plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json -DateKind String
if ([string]$Plan.plan_hash -ne $ExpectedPlanHash) {
    throw "Plan hash mismatch."
}
$Candidate = $Policy.next_long_campaign
if (
    [string]$Candidate.campaign_id -ne [string]$Plan.campaign_id -or
    [string]$Candidate.plan_hash -ne $ExpectedPlanHash -or
    [System.IO.Path]::GetFullPath([string]$Candidate.plan_path) -ne $PlanPath -or
    [string]$Candidate.plan_file_sha256 -ne (Get-Sha256 -Path $PlanPath)
) {
    throw "Policy/PlanOnly campaign binding mismatch."
}
$PostrunConfig = $Policy.dense_ws_postrun
if (-not $PostrunConfig -or $PostrunConfig.automatic_same_hash_through_materialization -ne $true) {
    throw "Dense WS automatic postrun is not enabled by policy."
}
if (
    [System.IO.Path]::GetFullPath([string]$PostrunConfig.orchestrator_path) -ne
        [System.IO.Path]::GetFullPath($PSCommandPath) -or
    [string]$PostrunConfig.orchestrator_sha256 -ne (Get-Sha256 -Path $PSCommandPath)
) {
    throw "Dense WS postrun orchestrator policy binding mismatch."
}
$RuntimeContract = $PostrunConfig.runtime_contract
if (-not $RuntimeContract -or [string]$RuntimeContract.status -ne "APPROVED") {
    throw "Dense WS postrun runtime contract is not approved."
}
if (
    [int]$RuntimeContract.total_max_runtime_sec -ne $TotalMaxRuntimeSec -or
    [int]$RuntimeContract.quality_max_runtime_sec -ne $QualityMaxRuntimeSec -or
    [int]$RuntimeContract.materialization_max_runtime_sec -ne
        $MaterializationMaxRuntimeSec -or
    $TotalMaxRuntimeSec -ne ($QualityMaxRuntimeSec + $MaterializationMaxRuntimeSec)
) {
    throw "Dense WS postrun runtime parameter/policy mismatch."
}
$RuntimeProposalPath = [System.IO.Path]::GetFullPath(
    [string]$RuntimeContract.proposal_path
)
$RuntimeApprovalPath = [System.IO.Path]::GetFullPath(
    [string]$RuntimeContract.approval_receipt_path
)
foreach ($runtimeBindingPath in @($RuntimeProposalPath, $RuntimeApprovalPath)) {
    if (-not (Test-Path -LiteralPath $runtimeBindingPath -PathType Leaf)) {
        throw "Dense WS runtime binding file is missing: $runtimeBindingPath"
    }
}
if (
    [string]$RuntimeContract.proposal_file_sha256 -ne
        (Get-Sha256 -Path $RuntimeProposalPath) -or
    [string]$RuntimeContract.approval_receipt_sha256 -ne
        (Get-Sha256 -Path $RuntimeApprovalPath)
) {
    throw "Dense WS runtime proposal/approval file hash mismatch."
}
if (
    [string]$RuntimeContract.quality_tool_sha256 -ne
        (Get-Sha256 -Path $QualityModule) -or
    [string]$RuntimeContract.materializer_tool_sha256 -ne
        (Get-Sha256 -Path $MaterializerModule)
) {
    throw "Dense WS quality/materializer code hash mismatch."
}
$RuntimeProposal = Get-Content -LiteralPath $RuntimeProposalPath -Raw |
    ConvertFrom-Json -DateKind String
$RuntimeApproval = Get-Content -LiteralPath $RuntimeApprovalPath -Raw |
    ConvertFrom-Json -DateKind String
if (
    [string]$RuntimeProposal.proposal_hash -ne [string]$RuntimeContract.proposal_hash -or
    [string]$RuntimeApproval.proposal_hash -ne [string]$RuntimeContract.proposal_hash -or
    [string]$RuntimeApproval.status -ne "APPROVED" -or
    $RuntimeApproval.runtime_contract_refreeze_authorized -ne $true -or
    $RuntimeApproval.evaluation_authorized -ne $false -or
    $RuntimeApproval.collector_plan_or_duration_change_authorized -ne $false -or
    $RuntimeApproval.venue_universe_signal_cost_risk_change_authorized -ne $false -or
    $RuntimeApproval.quality_or_materializer_code_change_authorized -ne $false -or
    [string]$RuntimeApproval.campaign_id -ne [string]$Plan.campaign_id -or
    [string]$RuntimeApproval.plan_hash -ne $ExpectedPlanHash -or
    [int]$RuntimeApproval.total_max_runtime_sec -ne $TotalMaxRuntimeSec -or
    [int]$RuntimeApproval.quality_max_runtime_sec -ne $QualityMaxRuntimeSec -or
    [int]$RuntimeApproval.materialization_max_runtime_sec -ne
        $MaterializationMaxRuntimeSec -or
    [string]$RuntimeApproval.postrun_not_before_local -ne
        [string]$RuntimeContract.postrun_not_before_local -or
    [string]$RuntimeApproval.postrun_hard_deadline_local -ne
        [string]$RuntimeContract.postrun_hard_deadline_local -or
    [string]$RuntimeApproval.quality_tool_sha256 -ne
        [string]$RuntimeContract.quality_tool_sha256 -or
    [string]$RuntimeApproval.materializer_tool_sha256 -ne
        [string]$RuntimeContract.materializer_tool_sha256
) {
    throw "Dense WS runtime proposal/approval semantic binding mismatch."
}
$PostrunNotBefore = ConvertFrom-IsoDateTimeOffset -Value (
    [string]$RuntimeContract.postrun_not_before_local
)
$PostrunHardDeadline = ConvertFrom-IsoDateTimeOffset -Value (
    [string]$RuntimeContract.postrun_hard_deadline_local
)
if ($PostrunNotBefore -ge $PostrunHardDeadline) {
    throw "Dense WS postrun runtime window is invalid."
}

$CampaignRoot = [System.IO.Path]::GetFullPath([string]$Plan.outputs.campaign_root)
$PostrunRoot = [System.IO.Path]::GetFullPath((Join-Path $CampaignRoot "_postrun"))
$Names = $PostrunConfig.output_names
$QualityReportPath = Get-OutputPath -Key "quality_report" -Names $Names -PostrunRoot $PostrunRoot
$LabelsOutputPath = Get-OutputPath -Key "regime_labels" -Names $Names -PostrunRoot $PostrunRoot
$SnapshotsOutputPath = Get-OutputPath -Key "execution_snapshots" -Names $Names -PostrunRoot $PostrunRoot
$MaterializationManifestPath = Get-OutputPath -Key "materialization_manifest" -Names $Names -PostrunRoot $PostrunRoot
$OwnerPath = Get-OutputPath -Key "owner" -Names $Names -PostrunRoot $PostrunRoot
$ReservationDefaultPath = Join-Path $PostrunRoot "launch-reservation.json"
$VisibleLogPath = Join-Path $PostrunRoot "postrun-visible.log"
$CampaignManifestPath = Join-Path $CampaignRoot "campaign-manifest.json"
$Python = Resolve-TradingMvpPython

$Guard = Get-Guard
$Disposition = $Guard.dense_ws_postrun_disposition
$allowedDecisions = @(
    "RUN_DENSE_WS_CAMPAIGN_DATA_QUALITY",
    "RUN_DENSE_WS_CAUSAL_MATERIALIZATION"
)
$preflightStatus = "BLOCKED"
$preflightReasons = [System.Collections.Generic.List[string]]::new()
$PreflightObservedAt = [DateTimeOffset]::Now
if ($PreflightObservedAt -lt $PostrunNotBefore) {
    $preflightReasons.Add("postrun_window_not_open")
}
if ($PreflightObservedAt -ge $PostrunHardDeadline) {
    $preflightReasons.Add("postrun_hard_deadline_passed")
}
if ([string]$Guard.usage.status -ne "AVAILABLE" -or [double]$Guard.usage.remaining_percent -le 15.0) {
    $preflightReasons.Add("weekly_quota_or_telemetry_block")
}
if ([string]$Guard.gate.run_id -ne [string]$Plan.campaign_id) {
    $preflightReasons.Add("active_gate_campaign_mismatch")
}
if ([string]$Guard.gate.status -ne "READY_FOR_POSTPROCESS") {
    $preflightReasons.Add("active_gate_not_ready_for_postprocess")
}
if ([string]$Disposition.campaign_id -ne [string]$Plan.campaign_id) {
    $preflightReasons.Add("postrun_disposition_campaign_mismatch")
}
if ([string]$Disposition.status -eq "RUNNING") {
    $preflightStatus = "ALREADY_RUNNING"
} elseif ([string]$Disposition.status -eq "MATERIALIZATION_ACCEPTED") {
    $preflightStatus = "COMPLETE"
} elseif ([string]$Disposition.status -in @(
    "QUALITY_REJECTED",
    "MATERIALIZATION_REJECTED"
)) {
    $preflightStatus = "COMPLETE_REJECTED"
} elseif ([string]$Disposition.status -in @(
    "STOPPED_INCOMPLETE",
    "INTEGRITY_CONFLICT"
)) {
    $preflightStatus = "RECOVERY_REQUIRES_EXACT_APPROVAL"
} elseif (
    $preflightReasons.Count -eq 0 -and
    [string]$Guard.decision -in $allowedDecisions -and
    [string]$Guard.next_action -eq "run_dense_ws_postrun_visible" -and
    [string]$Disposition.status -in @("QUALITY_MISSING", "QUALITY_ACCEPTED")
) {
    $preflightStatus = "READY"
} else {
    $preflightReasons.Add("authoritative_guard_does_not_dispatch_dense_ws_postrun")
}

$preflight = [ordered]@{
    schema = "trading_mvp_dense_ws_postrun_preflight_v1"
    status = $preflightStatus
    campaign_id = [string]$Plan.campaign_id
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    guard_decision = [string]$Guard.decision
    disposition_status = [string]$Disposition.status
    reasons = @($preflightReasons)
    runtime_contract = [ordered]@{
        total_max_runtime_sec = $TotalMaxRuntimeSec
        quality_max_runtime_sec = $QualityMaxRuntimeSec
        materialization_max_runtime_sec = $MaterializationMaxRuntimeSec
        postrun_not_before_local = $PostrunNotBefore.ToString("o")
        postrun_hard_deadline_local = $PostrunHardDeadline.ToString("o")
    }
    output_paths = [ordered]@{
        quality_report = $QualityReportPath
        regime_labels = $LabelsOutputPath
        execution_snapshots = $SnapshotsOutputPath
        materialization_manifest = $MaterializationManifestPath
        owner = $OwnerPath
    }
    no_run_or_output_writes = [bool]$PreflightOnly
}
if ($PreflightOnly) {
    if ($Json) {
        $preflight | ConvertTo-Json -Depth 16
    } else {
        $preflight | Format-List
    }
    exit 0
}
if ($preflightStatus -ne "READY") {
    throw "Dense WS postrun is not launchable: status=$preflightStatus reasons=$(@($preflightReasons) -join ',')."
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
                $candidateReservation = Get-Content -LiteralPath $ReservationPath -Raw |
                    ConvertFrom-Json -DateKind String
                if (
                    [int]$candidateReservation.expected_terminal_pid -eq $PID -and
                    [string]$candidateReservation.plan_hash -eq $ExpectedPlanHash -and
                    [System.IO.Path]::GetFullPath(
                        [string]$candidateReservation.policy_path
                    ) -eq $PolicyPath -and
                    [int]$candidateReservation.total_max_runtime_sec -eq
                        $TotalMaxRuntimeSec -and
                    [int]$candidateReservation.quality_max_runtime_sec -eq
                        $QualityMaxRuntimeSec -and
                    [int]$candidateReservation.materialization_max_runtime_sec -eq
                        $MaterializationMaxRuntimeSec -and
                    [string]$candidateReservation.postrun_hard_deadline_local -eq
                        $PostrunHardDeadline.ToString("o")
                ) {
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
    $owner = [ordered]@{
        schema = "trading_mvp_dense_ws_postrun_owner_v1"
        campaign_id = [string]$Plan.campaign_id
        plan_hash = $ExpectedPlanHash
        terminal_pid = $PID
        started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        stage = "STARTING"
        final = $false
        status = "RUNNING"
        total_max_runtime_sec = $TotalMaxRuntimeSec
        quality_max_runtime_sec = $QualityMaxRuntimeSec
        materialization_max_runtime_sec = $MaterializationMaxRuntimeSec
        postrun_hard_deadline_local = $PostrunHardDeadline.ToString("o")
    }
    Write-JsonCreateNew -Path $OwnerPath -Payload $owner
    if (Test-Path -LiteralPath $VisibleLogPath) {
        throw "Refusing to overwrite visible log: $VisibleLogPath"
    }
    [System.IO.File]::WriteAllText(
        $VisibleLogPath,
        "",
        [System.Text.UTF8Encoding]::new($false)
    )
    $StartedAt = [DateTimeOffset]::Now
    $TotalDeadline = Get-EarliestDeadline -Candidates @(
        $StartedAt.AddSeconds($TotalMaxRuntimeSec),
        $PostrunHardDeadline
    )
    if ($TotalDeadline -le $StartedAt) {
        throw "No bounded total runtime remains before the postrun hard deadline."
    }
    try {
        Write-VisibleLog "VISIBLE_DENSE_WS_POSTRUN_STARTED campaign_id=$($Plan.campaign_id)"
        if (-not (Test-Path -LiteralPath $CampaignManifestPath -PathType Leaf)) {
            throw "Campaign manifest is missing: $CampaignManifestPath"
        }
        if (-not (Test-Path -LiteralPath $QualityReportPath -PathType Leaf)) {
            $owner.stage = "CAMPAIGN_DATA_QUALITY"
            Write-JsonAtomic -Path $OwnerPath -Payload $owner
            $QualityDeadline = Get-EarliestDeadline -Candidates @(
                ([DateTimeOffset]::Now.AddSeconds($QualityMaxRuntimeSec)),
                $TotalDeadline,
                $PostrunHardDeadline
            )
            Invoke-BoundedPython -Stage "campaign-quality" -Deadline $QualityDeadline -Arguments @(
                "-u", $QualityModule,
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--campaign-manifest", $CampaignManifestPath,
                "--output", $QualityReportPath
            )
        }
        $quality = Get-Content -LiteralPath $QualityReportPath -Raw |
            ConvertFrom-Json -DateKind String
        if (
            [string]$quality.campaign_id -ne [string]$Plan.campaign_id -or
            [string]$quality.plan_hash -ne $ExpectedPlanHash
        ) {
            throw "Persisted campaign-quality binding mismatch."
        }
        if ($quality.accepted -ne $true) {
            if ([string]$quality.decision -ne "REJECT_DATA_QUALITY") {
                throw "Campaign-quality decision is inconsistent."
            }
            $owner.stage = "COMPLETE"
            $owner.final = $true
            $owner.status = "QUALITY_REJECTED"
            $owner.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
            Write-JsonAtomic -Path $OwnerPath -Payload $owner
            Write-VisibleLog "QUALITY_REJECTED; causal materialization was not started"
            return
        }

        $owner.stage = "CAUSAL_MATERIALIZATION"
        Write-JsonAtomic -Path $OwnerPath -Payload $owner
        $MaterializationDeadline = Get-EarliestDeadline -Candidates @(
            ([DateTimeOffset]::Now.AddSeconds($MaterializationMaxRuntimeSec)),
            $TotalDeadline,
            $PostrunHardDeadline
        )
        $remainingSec = [math]::Floor(
            ($MaterializationDeadline - [DateTimeOffset]::Now).TotalSeconds
        )
        if ($remainingSec -lt 1) {
            throw "No bounded runtime remains for causal materialization."
        }
        Invoke-BoundedPython -Stage "causal-materialization" -Deadline $MaterializationDeadline -Arguments @(
            "-u", $MaterializerModule,
            "--plan", $PlanPath,
            "--expected-plan-hash", $ExpectedPlanHash,
            "--quality-report", $QualityReportPath,
            "--labels-output", $LabelsOutputPath,
            "--snapshots-output", $SnapshotsOutputPath,
            "--manifest-output", $MaterializationManifestPath,
            "--max-runtime-sec", [string]$remainingSec
        )
        $materialization = Get-Content -LiteralPath $MaterializationManifestPath -Raw |
            ConvertFrom-Json -DateKind String
        if (
            [string]$materialization.campaign_id -ne [string]$Plan.campaign_id -or
            [string]$materialization.plan_hash -ne $ExpectedPlanHash
        ) {
            throw "Persisted materialization binding mismatch."
        }
        $owner.stage = "COMPLETE"
        $owner.final = $true
        $owner.status = if ($materialization.accepted -eq $true) {
            "COMPLETE"
        } else {
            "MATERIALIZATION_REJECTED"
        }
        $owner.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        Write-JsonAtomic -Path $OwnerPath -Payload $owner
        Write-VisibleLog "DENSE_WS_POSTRUN_COMPLETE decision=$($materialization.decision)"
    } catch {
        $owner.stage = "FAILED"
        $owner.final = $true
        $owner.status = "FAILED"
        $owner.error = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
        $owner.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        Write-JsonAtomic -Path $OwnerPath -Payload $owner
        Write-VisibleLog "DENSE_WS_POSTRUN_FAILED error=$($owner.error)"
        throw
    } finally {
        Write-Host "Visible postrun terminal remains open for inspection." -ForegroundColor DarkGray
    }
    return
}

[System.IO.Directory]::CreateDirectory($PostrunRoot) | Out-Null
$reservation = [ordered]@{
    schema = "trading_mvp_dense_ws_postrun_launch_reservation_v1"
    campaign_id = [string]$Plan.campaign_id
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    policy_path = $PolicyPath
    top_level_pid = $PID
    expected_terminal_pid = $null
    created_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    total_max_runtime_sec = $TotalMaxRuntimeSec
    quality_max_runtime_sec = $QualityMaxRuntimeSec
    materialization_max_runtime_sec = $MaterializationMaxRuntimeSec
    postrun_hard_deadline_local = $PostrunHardDeadline.ToString("o")
    final = $false
}
Write-JsonCreateNew -Path $ReservationDefaultPath -Payload $reservation

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$childArguments = @(
    "-NoExit",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $PSCommandPath,
    "-PlanPath", $PlanPath,
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-PolicyPath", $PolicyPath,
    "-TotalMaxRuntimeSec", [string]$TotalMaxRuntimeSec,
    "-QualityMaxRuntimeSec", [string]$QualityMaxRuntimeSec,
    "-MaterializationMaxRuntimeSec", [string]$MaterializationMaxRuntimeSec,
    "-VisibleChild",
    "-ReservationPath", $ReservationDefaultPath
)
try {
    $terminal = Start-Process `
        -FilePath $pwsh `
        -ArgumentList $childArguments `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Normal `
        -PassThru
} catch {
    Remove-Item -LiteralPath $ReservationDefaultPath -Force -ErrorAction SilentlyContinue
    throw
}
$reservation.expected_terminal_pid = $terminal.Id
$reservation.terminal_started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
Write-JsonAtomic -Path $ReservationDefaultPath -Payload $reservation

$ownershipVerified = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 500
    if (-not (Test-Path -LiteralPath $OwnerPath -PathType Leaf)) {
        continue
    }
    try {
        $observedOwner = Get-Content -LiteralPath $OwnerPath -Raw |
            ConvertFrom-Json -DateKind String
        if (
            [string]$observedOwner.campaign_id -eq [string]$Plan.campaign_id -and
            [string]$observedOwner.plan_hash -eq $ExpectedPlanHash -and
            [int]$observedOwner.terminal_pid -eq $terminal.Id -and
            $observedOwner.final -eq $false
        ) {
            $ownershipVerified = $true
            break
        }
    } catch {}
}
if (-not $ownershipVerified) {
    throw "Visible terminal launched but postrun ownership was not verified. Do not retry automatically."
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_postrun_visible_launch_v1"
    status = "VISIBLE_TERMINAL_LAUNCHED"
    campaign_id = [string]$Plan.campaign_id
    run_id = [string]$Plan.campaign_id
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    terminal_pid = $terminal.Id
    terminal_ownership_verified = $true
    owner_path = $OwnerPath
    reservation_path = $ReservationDefaultPath
    total_max_runtime_sec = $TotalMaxRuntimeSec
    quality_max_runtime_sec = $QualityMaxRuntimeSec
    materialization_max_runtime_sec = $MaterializationMaxRuntimeSec
    postrun_hard_deadline_local = $PostrunHardDeadline.ToString("o")
}
if ($Json) {
    $result | ConvertTo-Json -Depth 12
} else {
    $result | Format-List
}
