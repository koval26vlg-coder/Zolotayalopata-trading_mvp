param(
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\paper-public-readonly-probe-plan-v2.json",
    [string]$ExpectedPlanHash = "f2135b1059be438da5e1f9d2d48ce871e7012ad738a288716b521ed952dde9b6",
    [string]$StandingAuthorizationPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\trading-mvp-public-readonly-standing-authorization-v1.json",
    [string]$ExpectedStandingAuthorizationHash = "9b34452c59824c028ecb2016a1abd986238bc2f3119d9f838de4c5f238395ea5",
    [string]$CriticalAuthorizationPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\trading-mvp-public-readonly-v3-critical-authorization.json",
    [string]$ExpectedCriticalAuthorizationHash = "",
    [string]$FreshnessFailureAuditPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-07-30-1804-Codex-trading-mvp-public-probe-v2-stale-quote-critical.json",
    [ValidateRange(1, 180)][int]$MaxRuntimeSec = 180,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 45,
    [string]$ThreadId = "019e738a-b37c-7a33-ae04-6cc80739f184",
    [string]$UserAuthorizationText = "standing-policy automatic run authorization",
    [switch]$PlanOnly,
    [switch]$ConfirmedPublicProbe
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProbeModule = Join-Path $ProjectRoot "trading_mvp\src\paper_public_readonly_probe.py"
$WorkerScript = Join-Path $ProjectRoot "tools\run_paper_public_readonly_probe_visible.ps1"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
$AutopilotChecker = Join-Path $ProjectRoot "tools\check_trading_mvp_autopilot.ps1"
$GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
$CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json"
$RunGateRoot = Join-Path $ProjectRoot "docs\agent-log\run-gates"
$ArchiveRoot = Join-Path $ProjectRoot "docs\agent-log\archived-gates"
$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\public-readonly-probe-runs"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime with requests is unavailable. Set TRADING_MVP_PYTHON."
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 50 |
            Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Set-Property {
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

function Update-LaunchRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )
    $record = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-Property -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $Path -Value $record
}

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Invoke-JsonScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$Arguments = @()
    )
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $raw = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Script failed with exit code $LASTEXITCODE`: $ScriptPath"
    }
    return ((@($raw) -join [Environment]::NewLine) | ConvertFrom-Json)
}

foreach ($required in @(
    $ProbeModule,
    $WorkerScript,
    $GateChecker,
    $AutopilotChecker,
    $PlanPath,
    $StandingAuthorizationPath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file is missing: $required"
    }
}
$PlanPath = (Resolve-Path -LiteralPath $PlanPath).Path
$StandingAuthorizationPath = (
    Resolve-Path -LiteralPath $StandingAuthorizationPath
).Path
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$python = Resolve-Python
$env:TRADING_MVP_PYTHON = $python

$validationRaw = & $python -u $ProbeModule validate-plan `
    --plan $PlanPath `
    --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) {
    throw "Frozen public read-only probe plan validation failed."
}
$validation = ((@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json)
if ([string]$validation.plan_hash_sha256 -ne $ExpectedPlanHash) {
    throw "Validated plan hash does not match ExpectedPlanHash."
}
if ($MaxRuntimeSec -gt [int]$validation.max_runtime_sec) {
    throw "MaxRuntimeSec exceeds the frozen plan."
}
$planDocument = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
$planVersion = switch ([string]$planDocument.schema) {
    "trading_mvp_paper_public_readonly_probe_plan_v3" { "v3"; break }
    "trading_mvp_paper_public_readonly_probe_plan_v2" { "v2"; break }
    default { "v1" }
}
$standingValid = $false
$v3CriticalValid = $false
if ($planVersion -eq "v2") {
    $standingValidationRaw = & $python -u $ProbeModule `
        validate-plan-under-standing-authorization `
        --plan $PlanPath `
        --expected-plan-hash $ExpectedPlanHash `
        --standing-authorization $StandingAuthorizationPath `
        --expected-standing-authorization-hash `
            $ExpectedStandingAuthorizationHash
    if ($LASTEXITCODE -ne 0) {
        throw "Standing authorization does not authorize the v2 probe plan."
    }
    $standingValidation = (
        (@($standingValidationRaw) -join [Environment]::NewLine) |
            ConvertFrom-Json
    )
    $standingValid = (
        [string]$standingValidation.decision -eq
        "PLAN_AUTHORIZED_BY_STANDING_POLICY"
    )
} elseif ($planVersion -eq "v3") {
    foreach ($required in @(
        $CriticalAuthorizationPath,
        $FreshnessFailureAuditPath
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required v3 authorization file is missing: $required"
        }
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedCriticalAuthorizationHash)) {
        throw "ExpectedCriticalAuthorizationHash is required for v3."
    }
    $CriticalAuthorizationPath = (
        Resolve-Path -LiteralPath $CriticalAuthorizationPath
    ).Path
    $FreshnessFailureAuditPath = (
        Resolve-Path -LiteralPath $FreshnessFailureAuditPath
    ).Path
    $criticalValidationRaw = & $python -u $ProbeModule `
        validate-plan-under-v3-critical-authorization `
        --plan $PlanPath `
        --expected-plan-hash $ExpectedPlanHash `
        --standing-authorization $StandingAuthorizationPath `
        --expected-standing-authorization-hash `
            $ExpectedStandingAuthorizationHash `
        --critical-authorization $CriticalAuthorizationPath `
        --expected-critical-authorization-hash `
            $ExpectedCriticalAuthorizationHash `
        --failure-audit $FreshnessFailureAuditPath
    if ($LASTEXITCODE -ne 0) {
        throw "One-time critical authorization does not authorize the v3 probe plan."
    }
    $criticalValidation = (
        (@($criticalValidationRaw) -join [Environment]::NewLine) |
            ConvertFrom-Json
    )
    $v3CriticalValid = (
        [string]$criticalValidation.decision -eq
        "PLAN_AUTHORIZED_BY_ONE_TIME_V3_CRITICAL_APPROVAL"
    )
    $standingValid = $v3CriticalValid
}

$gate = Invoke-JsonScript -ScriptPath $GateChecker -Arguments @("-Json")
$gateStatus = if ($gate.gate_status) {
    [string]$gate.gate_status
} else {
    [string]$gate.status
}
if ($gateStatus -eq "RUNNING") {
    throw "Public probe blocked by active RUNNING gate run_id=$($gate.run_id)."
}
$stoppedSupersedeAllowed = $false
if ($gateStatus -eq "STOPPED_INCOMPLETE") {
    $gateDocument = Get-Content -LiteralPath $GatePath -Raw |
        ConvertFrom-Json
    $pidCandidates = @(
        $gateDocument.collector_pid,
        $gateDocument.monitor_pid,
        @($gateDocument.process_ids)
    ) |
        ForEach-Object { if ($_ -ne $null) { [int]$_ } } |
        Sort-Object -Unique
    foreach ($candidatePid in $pidCandidates) {
        if (Get-Process -Id $candidatePid -ErrorAction SilentlyContinue) {
            throw "Stopped source writer PID is still alive: $candidatePid"
        }
    }
    $sourceManifestPath = [System.IO.Path]::GetFullPath(
        [string]$gateDocument.manifest_path
    )
    if ($planVersion -eq "v2") {
        $sourceRunId = "paper_public_readonly_probe_20260730_142851"
        $sourcePlanHash = "318c6dbd76777cc4cff8f8e4e0ec67df10b497b33709155c642d2476285527ff"
        if (-not $standingValid -or [string]$gate.run_id -ne $sourceRunId) {
            throw "STOPPED_INCOMPLETE is not the exact authorized v2 migration source."
        }
        $null = & $python -u $ProbeModule validate-result `
            --manifest $sourceManifestPath `
            --expected-plan-hash $sourcePlanHash
        if ($LASTEXITCODE -ne 0) {
            throw "Stopped v1 migration manifest failed immutable validation."
        }
        $sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw |
            ConvertFrom-Json
        if (
            [string]$sourceManifest.run_id -ne $sourceRunId -or
            [string]$sourceManifest.status -ne "STOPPED_INCOMPLETE" -or
            $sourceManifest.final -ne $false -or
            [string]$sourceManifest.quality.hard_stop_reason -ne
                "schema_mismatch"
        ) {
            throw "Stopped source is not the exact MEXC schema incident."
        }
        $v2Contract = Get-Content -LiteralPath (
            [string]$planDocument.contract.path
        ) -Raw | ConvertFrom-Json
        $boundSourceManifest = [System.IO.Path]::GetFullPath(
            [string]$v2Contract.migration_evidence.source_probe_manifest.path
        )
        if ($boundSourceManifest -ne $sourceManifestPath) {
            throw "v2 contract is not bound to the stopped migration manifest."
        }
    } elseif ($planVersion -eq "v3") {
        $sourceRunId = "paper_public_readonly_probe_v2_20260730_145817"
        $sourcePlanHash = "f2135b1059be438da5e1f9d2d48ce871e7012ad738a288716b521ed952dde9b6"
        $expectedFailureAuditHash = "18a0f33b0c3eb3add4652ef7e53d75184bfaaf44c5dca0a98a933e9426fb2f0a"
        if (
            -not $v3CriticalValid -or
            [string]$gate.run_id -ne $sourceRunId
        ) {
            throw "STOPPED_INCOMPLETE is not the exact authorized v3 freshness source."
        }
        $observedFailureAuditHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $FreshnessFailureAuditPath
        ).Hash.ToLowerInvariant()
        if ($observedFailureAuditHash -ne $expectedFailureAuditHash) {
            throw "v3 freshness failure audit hash mismatch."
        }
        $null = & $python -u $ProbeModule validate-result `
            --manifest $sourceManifestPath `
            --expected-plan-hash $sourcePlanHash
        if ($LASTEXITCODE -ne 0) {
            throw "Stopped v2 freshness manifest failed immutable validation."
        }
        $v3Contract = Get-Content -LiteralPath (
            [string]$planDocument.contract.path
        ) -Raw | ConvertFrom-Json
        $boundSourceManifest = [System.IO.Path]::GetFullPath(
            [string]$v3Contract.migration_evidence.source_probe_manifest.path
        )
        $boundFailureAudit = [System.IO.Path]::GetFullPath(
            [string]$v3Contract.migration_evidence.source_failure_audit.path
        )
        if (
            $boundSourceManifest -ne $sourceManifestPath -or
            $boundFailureAudit -ne $FreshnessFailureAuditPath
        ) {
            throw "v3 contract is not bound to the stopped freshness evidence."
        }
    } else {
        throw "STOPPED_INCOMPLETE cannot be superseded by this plan version."
    }
    $stoppedSupersedeAllowed = $true
}

$autopilot = Invoke-JsonScript -ScriptPath $AutopilotChecker -Arguments @("-Json")
$remainingPercent = [double]$autopilot.usage.remaining_percent
$checkpoint = $autopilot.research_fallback.critical_checkpoint
$checkpointHash = if ($checkpoint) {
    [string]$checkpoint.plan_hash_sha256
} else {
    ""
}
if ($remainingPercent -le 15.0) {
    throw "Weekly remaining_percent=$remainingPercent does not permit a new probe."
}
if ([string]$autopilot.usage.status -ne "AVAILABLE") {
    throw "Weekly usage telemetry is unavailable or stale."
}
if ($planVersion -eq "v1") {
    if (
        [string]$autopilot.decision -ne "USER_REVIEW_REQUIRED" -or
        [string]$autopilot.next_action -ne
            "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE" -or
        $checkpointHash -ne $ExpectedPlanHash
    ) {
        throw "Autopilot guard does not expose the expected v1 probe checkpoint."
    }
} elseif ($planVersion -eq "v2" -and -not $standingValid) {
    throw "The v2 probe plan lacks a valid standing authorization."
} elseif ($planVersion -eq "v3" -and -not $v3CriticalValid) {
    throw "The v3 probe plan lacks a valid one-time critical authorization."
}
$scheduleStatus = [string]$autopilot.schedule_window.status
$scheduleEtaSec = if ($null -ne $autopilot.schedule_window.eta_sec) {
    [int]$autopilot.schedule_window.eta_sec
} else {
    [int]::MaxValue
}
if ($scheduleStatus -eq "DUE" -or $scheduleEtaSec -le 300) {
    throw "Approved PIT segment is due or starts within five minutes and has priority."
}

$launchCommand = @(
    "pwsh -NoProfile -ExecutionPolicy Bypass -File",
    (Quote-PowerShellLiteral -Value $PSCommandPath),
    "-PlanPath", (Quote-PowerShellLiteral -Value $PlanPath),
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-StandingAuthorizationPath",
        (Quote-PowerShellLiteral -Value $StandingAuthorizationPath),
    "-ExpectedStandingAuthorizationHash",
        $ExpectedStandingAuthorizationHash,
    "-MaxRuntimeSec", $MaxRuntimeSec,
    "-HoldOpenSec", $HoldOpenSec
) -join " "
if ($planVersion -eq "v3") {
    $launchCommand += @(
        " -CriticalAuthorizationPath ",
        (Quote-PowerShellLiteral -Value $CriticalAuthorizationPath),
        " -ExpectedCriticalAuthorizationHash ",
        $ExpectedCriticalAuthorizationHash,
        " -FreshnessFailureAuditPath ",
        (Quote-PowerShellLiteral -Value $FreshnessFailureAuditPath)
    ) -join ""
}
if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_paper_public_readonly_probe_visible_preview_$planVersion"
        mode = "PlanOnly"
        decision = if ($v3CriticalValid) {
            "AUTHORIZED_BY_ONE_TIME_V3_CRITICAL_APPROVAL_READY_FOR_VISIBLE_START"
        } elseif ($standingValid) {
            "AUTHORIZED_BY_STANDING_POLICY_READY_FOR_VISIBLE_START"
        } else {
            "AWAIT_EXPLICIT_PUBLIC_READONLY_PROBE_APPROVAL"
        }
        plan_path = $PlanPath
        plan_file_sha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath
        ).Hash.ToLowerInvariant()
        plan_hash_sha256 = $ExpectedPlanHash
        runtime_module_sha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $ProbeModule
        ).Hash.ToLowerInvariant()
        worker_script_sha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $WorkerScript
        ).Hash.ToLowerInvariant()
        duration_sec = 120
        max_runtime_sec = $MaxRuntimeSec
        venues = @("mexc", "gateio")
        output_namespace = $OutputRoot
        weekly_remaining_percent = $remainingPercent
        gate_status = $gateStatus
        stopped_migration_supersede_allowed = $stoppedSupersedeAllowed
        standing_authorization_path = $StandingAuthorizationPath
        standing_authorization_hash_sha256 = (
            $ExpectedStandingAuthorizationHash
        )
        critical_authorization_path = if ($planVersion -eq "v3") {
            $CriticalAuthorizationPath
        } else {
            $null
        }
        critical_authorization_hash_sha256 = if ($planVersion -eq "v3") {
            $ExpectedCriticalAuthorizationHash
        } else {
            $null
        }
        freshness_failure_audit_path = if ($planVersion -eq "v3") {
            $FreshnessFailureAuditPath
        } else {
            $null
        }
        visible_terminal_required = $true
        network_requests_performed = 0
        private_api_keys = $false
        live_orders = $false
        leverage_or_margin = $false
        launch_command = $launchCommand
    } | ConvertTo-Json -Depth 12
    exit 0
}
if ($planVersion -eq "v1" -and -not $ConfirmedPublicProbe) {
    throw "ConfirmedPublicProbe is required. Run -PlanOnly first."
}
if (-not $UserAuthorizationText.Trim()) {
    throw "UserAuthorizationText is required."
}

if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
    foreach ($directory in Get-ChildItem -LiteralPath $OutputRoot -Directory) {
        $manifest = Join-Path $directory.FullName "manifest.json"
        if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { continue }
        try {
            $cached = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
            if (
                [string]$cached.plan.plan_hash_sha256 -ne $ExpectedPlanHash
            ) {
                continue
            }
            $null = & $python -u $ProbeModule validate-result `
                --manifest $manifest `
                --expected-plan-hash $ExpectedPlanHash 2>$null
            if ($LASTEXITCODE -ne 0) {
                throw "Existing same-plan manifest failed validation: $manifest"
            }
            if (
                $cached.final -eq $true -and
                [string]$cached.verdict -eq "PUBLIC_READONLY_PROBE_ACCEPTED"
            ) {
                [ordered]@{
                    decision = "VALID_FINAL_PUBLIC_PROBE_CACHE_REUSED_NO_DUPLICATE_LAUNCH"
                    run_id = [string]$cached.run_id
                    plan_hash_sha256 = $ExpectedPlanHash
                    manifest_path = $manifest
                    deterministic_result_hash = [string]$cached.deterministic_result_hash
                    visible_terminal_started = $false
                } | ConvertTo-Json -Depth 8
                exit 0
            }
            throw "The standing policy permits only one run per plan hash; prior attempt exists: $manifest"
        } catch {
            if (
                $_.Exception.Message -like
                    "The standing policy permits only one run*" -or
                $_.Exception.Message -like
                    "Existing same-plan manifest failed validation*"
            ) {
                throw
            }
            continue
        }
    }
}

New-Item -ItemType Directory -Force -Path $RunGateRoot, $ArchiveRoot, $OutputRoot |
    Out-Null
$runTimestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd_HHmmss")
$RunId = "paper_public_readonly_probe_${planVersion}_$runTimestamp"
$OutputDir = Join-Path $OutputRoot $RunId
$AuthorizationPath = Join-Path $OutputDir "authorization.json"
$ManifestPath = Join-Path $OutputDir "manifest.json"
$LogPath = Join-Path $OutputDir "visible.log"
$LaunchRecordPath = Join-Path $RunGateRoot "$RunId.public-readonly-probe.visible-launch.json"
if (Test-Path -LiteralPath $OutputDir) {
    throw "Refusing to reuse public probe output directory: $OutputDir"
}
if (Test-Path -LiteralPath $LaunchRecordPath) {
    throw "Refusing to overwrite public probe launch record: $LaunchRecordPath"
}

$authorizationArguments = @(
    "-u", $ProbeModule, "authorize",
    "--plan", $PlanPath,
    "--expected-plan-hash", $ExpectedPlanHash,
    "--run-id", $RunId,
    "--user-instruction", $UserAuthorizationText,
    "--thread-id", $ThreadId,
    "--output", $AuthorizationPath
)
if ($planVersion -eq "v2") {
    $authorizationArguments += @(
        "--standing-authorization", $StandingAuthorizationPath,
        "--expected-standing-authorization-hash",
            $ExpectedStandingAuthorizationHash
    )
} elseif ($planVersion -eq "v3") {
    $authorizationArguments += @(
        "--standing-authorization", $StandingAuthorizationPath,
        "--expected-standing-authorization-hash",
            $ExpectedStandingAuthorizationHash,
        "--critical-authorization", $CriticalAuthorizationPath,
        "--expected-critical-authorization-hash",
            $ExpectedCriticalAuthorizationHash,
        "--freshness-failure-audit", $FreshnessFailureAuditPath
    )
}
$authorizationRaw = & $python @authorizationArguments
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create immutable user authorization evidence."
}
$authorization = (
    (@($authorizationRaw) -join [Environment]::NewLine) | ConvertFrom-Json
)
$AuthorizationHash = [string]$authorization.authorization_hash_sha256
if ($AuthorizationHash.Length -ne 64) {
    throw "Authorization hash is invalid."
}

$archiveStamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd_HHmmss_fff")
$GateArchivePath = Join-Path $ArchiveRoot (
    "active-run-gate.$($gate.run_id).superseded-by-$RunId.$archiveStamp.json"
)
$PointerArchivePath = Join-Path $ArchiveRoot (
    "current-run.$($gate.run_id).superseded-by-$RunId.$archiveStamp.json"
)
if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
    Copy-Item -LiteralPath $GatePath -Destination $GateArchivePath
}
if (Test-Path -LiteralPath $CurrentRunPath -PathType Leaf) {
    Copy-Item -LiteralPath $CurrentRunPath -Destination $PointerArchivePath
}

$createdAt = [DateTimeOffset]::Now
$launchRecord = [ordered]@{
    schema = "trading_mvp_paper_public_readonly_probe_visible_launch_$planVersion"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    gate_status = "LAUNCHING"
    final = $false
    created_at = $createdAt.ToString("o")
    plan_path = $PlanPath
    plan_file_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath
    ).Hash.ToLowerInvariant()
    plan_hash_sha256 = $ExpectedPlanHash
    authorization_path = $AuthorizationPath
    authorization_file_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $AuthorizationPath
    ).Hash.ToLowerInvariant()
    authorization_hash_sha256 = $AuthorizationHash
    authorization_action = "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE"
    authorization_basis = if ($planVersion -eq "v3") {
        "hash_bound_standing_limits_plus_one_time_v3_critical_authorization"
    } elseif ($planVersion -eq "v2") {
        "hash_bound_standing_authorization"
    } else {
        "explicit_user_instruction_in_current_thread"
    }
    standing_authorization_path = if ($planVersion -in @("v2", "v3")) {
        $StandingAuthorizationPath
    } else {
        $null
    }
    standing_authorization_hash_sha256 = if ($planVersion -in @("v2", "v3")) {
        $ExpectedStandingAuthorizationHash
    } else {
        $null
    }
    critical_authorization_path = if ($planVersion -eq "v3") {
        $CriticalAuthorizationPath
    } else {
        $null
    }
    critical_authorization_hash_sha256 = if ($planVersion -eq "v3") {
        $ExpectedCriticalAuthorizationHash
    } else {
        $null
    }
    freshness_failure_audit_path = if ($planVersion -eq "v3") {
        $FreshnessFailureAuditPath
    } else {
        $null
    }
    runtime_module_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ProbeModule
    ).Hash.ToLowerInvariant()
    worker_script_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $WorkerScript
    ).Hash.ToLowerInvariant()
    output = [ordered]@{ path = $OutputDir; kind = "directory" }
    manifest_path = $ManifestPath
    log_path = $LogPath
    gate_path = $GatePath
    current_run_path = $CurrentRunPath
    prior_gate_archive_path = $GateArchivePath
    prior_pointer_archive_path = $PointerArchivePath
    requested_duration_sec = 120
    max_runtime_sec = $MaxRuntimeSec
    expected_duration_sec = 120
    visible_terminal = $true
    public_api_only = $true
    maximum_public_get_attempts = 576
    auto_resume = $false
    replay_allowed = $false
    grid_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord

$workerCommand = @(
    "& $(Quote-PowerShellLiteral -Value $WorkerScript)",
    "-PlanPath $(Quote-PowerShellLiteral -Value $PlanPath)",
    "-ExpectedPlanHash $(Quote-PowerShellLiteral -Value $ExpectedPlanHash)",
    "-AuthorizationPath $(Quote-PowerShellLiteral -Value $AuthorizationPath)",
    "-ExpectedAuthorizationHash $(Quote-PowerShellLiteral -Value $AuthorizationHash)",
    "-OutputDir $(Quote-PowerShellLiteral -Value $OutputDir)",
    "-RunId $(Quote-PowerShellLiteral -Value $RunId)",
    "-MaxRuntimeSec $MaxRuntimeSec",
    "-HoldOpenSec $HoldOpenSec",
    "-GatePath $(Quote-PowerShellLiteral -Value $GatePath)",
    "-CurrentRunPath $(Quote-PowerShellLiteral -Value $CurrentRunPath)",
    "-LaunchRecordPath $(Quote-PowerShellLiteral -Value $LaunchRecordPath)",
    "-LogPath $(Quote-PowerShellLiteral -Value $LogPath)"
) -join " "
$encoded = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($workerCommand)
)
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
try {
    $process = Start-Process -FilePath $pwsh `
        -ArgumentList @("-NoLogo", "-NoProfile", "-EncodedCommand", $encoded) `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Normal `
        -PassThru
    Update-LaunchRecord -Path $LaunchRecordPath -Values @{
        launcher_pid = $PID
        worker_pid = $process.Id
        collector_pid = $process.Id
        process_ids = @($process.Id)
        started_at = [DateTimeOffset]::Now.ToString("o")
    }
} catch {
    Update-LaunchRecord -Path $LaunchRecordPath -Values @{
        status = "STOPPED_INCOMPLETE"
        gate_status = "STOPPED_INCOMPLETE"
        final = $false
        failure = $_.Exception.Message
        completed_at = [DateTimeOffset]::Now.ToString("o")
    }
    throw
}

[ordered]@{
    decision = "VISIBLE_PUBLIC_READONLY_PROBE_STARTED"
    run_id = $RunId
    plan_hash_sha256 = $ExpectedPlanHash
    authorization_hash_sha256 = $AuthorizationHash
    standing_authorization_hash_sha256 = if ($planVersion -in @("v2", "v3")) {
        $ExpectedStandingAuthorizationHash
    } else {
        $null
    }
    critical_authorization_hash_sha256 = if ($planVersion -eq "v3") {
        $ExpectedCriticalAuthorizationHash
    } else {
        $null
    }
    worker_pid = $process.Id
    output_dir = $OutputDir
    manifest_path = $ManifestPath
    launch_record_path = $LaunchRecordPath
    log_path = $LogPath
    expected_finish = $createdAt.AddSeconds($MaxRuntimeSec).ToString("o")
    visible_terminal = $true
    auto_resume = $false
} | ConvertTo-Json -Depth 10
