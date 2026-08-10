param(
    [switch]$PreflightOnly,
    [switch]$VisibleWorker
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcherFileName = "start_funding_unrestricted_metadata_discovery_visible.ps1"
$runtimeModule = Join-Path $repoRoot "trading_mvp\src\funding_unrestricted_metadata_discovery.py"
$writerClaimCli = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"
$autopilotChecker = Join-Path $repoRoot "tools\check_trading_mvp_autopilot.ps1"
$activeRunChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$runtimeManifestPath = Join-Path $repoRoot "docs\plans\funding-unrestricted-metadata-discovery-runtime-manifest-20260810-v2.json"
$globalWriterClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$globalWriterClaimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$runId = "funding_unrestricted_metadata_discovery_20260810_v2"
$launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\$runId.launch.json"
$failureDiagnosticPath = Join-Path $repoRoot "docs\agent-log\run-gates\$runId.runtime-failure.json"
$outputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\funding-unrestricted-metadata-discovery\$runId"
$proposalPath = $null
$receiptPath = $null
$expectedProposalFileSha256 = $null
$expectedProposalHash = $null
$allowedEndpointUrls = @(
    "https://contract.mexc.com/api/v1/contract/detail",
    "https://api.gateio.ws/api/v4/futures/usdt/contracts"
)
$maxRuntimeSec = 300
$hardOutputCapBytes = 50000000

function ConvertFrom-JsonPreserveDateStrings {
    param([Parameter(Mandatory = $true)][AllowEmptyString()]$InputJson)

    $text = @($InputJson) -join [Environment]::NewLine
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        return $text | ConvertFrom-Json -DateKind String
    }
    return $text | ConvertFrom-Json
}

function Resolve-ProjectPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
        "D:\AionUi-Paperclip\.venv-sml\Scripts\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe"
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "No usable Python runtime is available."
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-SamePath {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return [string]::Equals(
        [System.IO.Path]::GetFullPath($Left),
        [System.IO.Path]::GetFullPath($Right),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Get-RuntimeManifestBinding {
    if (-not (Test-Path -LiteralPath $runtimeManifestPath -PathType Leaf)) {
        throw "Diagnostic v2 runtime manifest is missing. Exact approval is required."
    }
    $manifest = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $runtimeManifestPath
    )
    if (
        [string]$manifest.schema -ne
        "trading_mvp_funding_unrestricted_metadata_discovery_runtime_manifest_v2" -or
        [string]$manifest.status -ne "FROZEN_WITH_EXACT_SINGLE_USE_APPROVAL" -or
        [string]$manifest.run_id -ne $runId
    ) {
        throw "Diagnostic v2 runtime manifest identity mismatch."
    }
    if (-not $manifest.proposal -or -not $manifest.approval_receipt -or -not $manifest.execution) {
        throw "Diagnostic v2 runtime manifest bindings are incomplete."
    }
    foreach ($value in @(
        [string]$manifest.proposal.file_sha256,
        [string]$manifest.proposal.proposal_hash
    )) {
        if ($value -notmatch '^[0-9a-f]{64}$') {
            throw "Diagnostic v2 proposal hash binding is invalid."
        }
    }
    if (-not (Test-SamePath -Left ([string]$manifest.execution.output_path) -Right $outputPath)) {
        throw "Diagnostic v2 output path binding mismatch."
    }
    if (-not (Test-SamePath `
        -Left ([string]$manifest.execution.failure_diagnostic_path) `
        -Right $failureDiagnosticPath
    )) {
        throw "Diagnostic v2 failure path binding mismatch."
    }
    return $manifest
}

function Assert-ExactPropertySet {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $observed = @($Object.PSObject.Properties.Name | Sort-Object)
    $required = @($Expected | Sort-Object)
    if ((Compare-Object -ReferenceObject $required -DifferenceObject $observed).Count -ne 0) {
        throw "$Label property set changed."
    }
}

function Read-RuntimeFailureDiagnostic {
    if (-not (Test-Path -LiteralPath $failureDiagnosticPath -PathType Leaf)) {
        throw "Runtime failure diagnostic is missing."
    }
    $file = Get-Item -LiteralPath $failureDiagnosticPath
    if ($file.Length -le 0 -or $file.Length -gt 16384) {
        throw "Runtime failure diagnostic byte cap changed."
    }
    $arguments = @(Get-RuntimeArguments) + @("--validate-failure-diagnostic-only")
    $diagnostic = Invoke-PythonJson -Arguments $arguments
    Assert-ExactPropertySet -Object $diagnostic -Label "failure diagnostic" -Expected @(
        "schema", "status", "run_id", "failure_hash", "failure",
        "raw_payload_persisted", "funding_rates_persisted", "prices_persisted",
        "retry_authorized"
    )
    Assert-ExactPropertySet -Object $diagnostic.failure -Label "failure detail" -Expected @(
        "category", "stage", "endpoint_id", "exception_type", "http_status",
        "attempt", "request_count"
    )
    if (
        [string]$diagnostic.schema -ne "trading_mvp_funding_metadata_failure_validation_v2" -or
        [string]$diagnostic.status -ne "VALIDATED_ALLOWLISTED_FAILURE" -or
        [string]$diagnostic.run_id -ne $runId -or
        $diagnostic.raw_payload_persisted -ne $false -or
        $diagnostic.funding_rates_persisted -ne $false -or
        $diagnostic.prices_persisted -ne $false -or
        $diagnostic.retry_authorized -ne $false -or
        [string]$diagnostic.failure_hash -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Runtime failure diagnostic safety contract changed."
    }
    return [ordered]@{
        path = $failureDiagnosticPath
        file_sha256 = Get-Sha256 -Path $failureDiagnosticPath
        failure_hash = [string]$diagnostic.failure_hash
        failure = $diagnostic.failure
        raw_payload_persisted = $false
        funding_rates_persisted = $false
        prices_persisted = $false
        retry_authorized = $false
    }
}

function Test-ProcessAlive {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return $false
    }
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function New-LaunchRecordExclusive {
    param([Parameter(Mandatory = $true)]$Object)

    $parent = Split-Path -Parent $launchRecordPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $raw = ($Object | ConvertTo-Json -Depth 20) + [Environment]::NewLine
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($raw)
    try {
        $stream = [System.IO.File]::Open(
            $launchRecordPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read
        )
    } catch [System.IO.IOException] {
        throw "Exact launch record already exists; duplicate launch is forbidden."
    }
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
}

function Set-LaunchStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Message = ""
    )

    $script:launchRecord.status = $Status
    $script:launchRecord.message = $Message
    $script:launchRecord.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    $script:launchRecord.visible_terminal_pid = $PID
    Write-JsonAtomic -Object $script:launchRecord -Path $launchRecordPath
}

function Invoke-PythonJson {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $raw = @(& $script:python @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $(@($raw) -join ' ')"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $raw
}

function Get-RuntimeArguments {
    return @(
        $runtimeModule,
        "--repo-root", $repoRoot,
        "--proposal-path", $proposalPath,
        "--expected-proposal-file-sha256", $expectedProposalFileSha256,
        "--expected-proposal-hash", $expectedProposalHash,
        "--receipt-path", $receiptPath,
        "--runtime-manifest-path", $runtimeManifestPath,
        "--output-path", $outputPath,
        "--run-id", $runId,
        "--failure-diagnostic-path", $failureDiagnosticPath
    )
}

function Invoke-RuntimePreflight {
    $arguments = @(Get-RuntimeArguments) + @("--preflight-only")
    return Invoke-PythonJson -Arguments $arguments
}

function Invoke-GuardPreflight {
    $autopilotRaw = @(& pwsh -NoProfile -ExecutionPolicy Bypass -File $autopilotChecker -Json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot guard failed: $(@($autopilotRaw) -join ' ')"
    }
    $autopilot = ConvertFrom-JsonPreserveDateStrings -InputJson $autopilotRaw
    if ([string]$autopilot.status -ne "ACTIVE") {
        throw "Autopilot guard is not ACTIVE: $($autopilot.status)"
    }
    if ($autopilot.stop_new_actions -ne $false) {
        throw "Autopilot guard forbids new actions."
    }
    if ([string]$autopilot.usage.status -ne "AVAILABLE") {
        throw "Weekly telemetry is unavailable or stale."
    }
    if ([double]$autopilot.usage.remaining_percent -le 15.0) {
        throw "Weekly remaining percentage is at or below 15."
    }

    $gateRaw = @(& pwsh -NoProfile -ExecutionPolicy Bypass -File $activeRunChecker -Json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Active-run gate failed: $(@($gateRaw) -join ' ')"
    }
    $gate = ConvertFrom-JsonPreserveDateStrings -InputJson $gateRaw
    if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        throw "Active-run gate blocks metadata discovery: $($gate.status)"
    }
    if (Test-Path -LiteralPath $globalWriterClaimPath -PathType Leaf) {
        throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS: owner reconciliation is required."
    }
    return [ordered]@{
        autopilot_status = [string]$autopilot.status
        autopilot_decision = [string]$autopilot.decision
        weekly_remaining_percent = [double]$autopilot.usage.remaining_percent
        gate_status = [string]$gate.status
        gate_run_id = [string]$gate.run_id
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    }
}

function Get-ExistingLaunchDisposition {
    if (-not (Test-Path -LiteralPath $launchRecordPath -PathType Leaf)) {
        return $null
    }
    try {
        $record = ConvertFrom-JsonPreserveDateStrings -InputJson (
            Get-Content -Raw -LiteralPath $launchRecordPath
        )
    } catch {
        throw "Existing launch record is unreadable; fail-closed review is required."
    }
    if ([string]$record.run_id -ne $runId) {
        throw "Existing launch record has a mismatched run_id."
    }
    $status = [string]$record.status
    $ownerAlive = Test-ProcessAlive -ProcessId ([int]$record.visible_terminal_pid)
    if ($status -eq "COMPLETE") {
        return [ordered]@{ status = "ALREADY_COMPLETE"; record = $record }
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "STOPPED_INCOMPLETE is terminal; retry is not authorized."
    }
    if ($ownerAlive) {
        return [ordered]@{ status = "ALREADY_RUNNING"; record = $record }
    }
    throw "A nonterminal launch record has no live owner; retry is not authorized."
}

function Invoke-FullPreflight {
    param([switch]$IgnoreOwnLaunchRecord)

    foreach ($required in @(
        $runtimeModule,
        $writerClaimCli,
        $autopilotChecker,
        $activeRunChecker,
        $proposalPath,
        $receiptPath,
        $runtimeManifestPath
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required frozen runtime file is missing: $required"
        }
    }
    if ((Split-Path -Leaf $PSCommandPath) -ne $launcherFileName) {
        throw "The metadata discovery must run through its exact top-level launcher."
    }
    if (Test-Path -LiteralPath $failureDiagnosticPath -PathType Leaf) {
        throw "STOPPED_INCOMPLETE failure diagnostic exists; this exact run is terminal."
    }

    if (-not $IgnoreOwnLaunchRecord) {
        $existing = Get-ExistingLaunchDisposition
        if ($existing) {
            return [ordered]@{
                schema = "trading_mvp_funding_metadata_visible_preflight_v2"
                status = [string]$existing.status
                run_id = $runId
                launch_record_path = $launchRecordPath
                failure_diagnostic_path = $failureDiagnosticPath
                output_path = $outputPath
                network_requested = $false
            }
        }
    }

    $guard = Invoke-GuardPreflight
    $runtime = Invoke-RuntimePreflight
    if ([string]$runtime.status -eq "ALREADY_COMPLETE_IMMUTABLE_NO_NETWORK") {
        return [ordered]@{
            schema = "trading_mvp_funding_metadata_visible_preflight_v2"
            status = "ALREADY_COMPLETE"
            run_id = $runId
            guard = $guard
            runtime = $runtime
            launch_record_path = $launchRecordPath
            failure_diagnostic_path = $failureDiagnosticPath
            output_path = $outputPath
            network_requested = $false
        }
    }
    if ([string]$runtime.status -ne "PREFLIGHT_OK_NO_NETWORK") {
        throw "Runtime preflight did not return PREFLIGHT_OK_NO_NETWORK."
    }
    return [ordered]@{
        schema = "trading_mvp_funding_metadata_visible_preflight_v2"
        status = "READY_FOR_VISIBLE_SINGLE_USE"
        run_id = $runId
        guard = $guard
        runtime = $runtime
        launch_record_path = $launchRecordPath
        failure_diagnostic_path = $failureDiagnosticPath
        output_path = $outputPath
        max_runtime_sec = $maxRuntimeSec
        hard_output_cap_bytes = $hardOutputCapBytes
        maximum_total_http_requests = 4
        network_requested = $false
    }
}

function New-GlobalWriterClaim {
    $raw = @(& $script:python $writerClaimCli `
        "claim" `
        "--path" $globalWriterClaimPath `
        "--run-id" $runId `
        "--owner-pid" ([string]$PID) `
        "--owner-kind" "funding_metadata_visible_worker" `
        "--plan-hash" $expectedProposalHash `
        "--output-namespace" $outputPath `
        "--terminal-pid" ([string]$PID) 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "GLOBAL_MARKET_WRITER_CLAIM_EXISTS_OR_FAILED: $(@($raw) -join ' ')"
    }
    $claim = ConvertFrom-JsonPreserveDateStrings -InputJson $raw
    if (
        [string]$claim.run_id -ne $runId -or
        [int]$claim.owner_pid -ne $PID -or
        [string]$claim.ownership_token -notmatch '^[0-9a-f]{32}$'
    ) {
        throw "Global writer claim identity mismatch."
    }
    return $claim
}

function Set-GlobalWriterProcess {
    param(
        [Parameter(Mandatory = $true)][string]$OwnershipToken,
        [Parameter(Mandatory = $true)][int]$WriterPid
    )

    $raw = @(& $script:python $writerClaimCli `
        "attach" `
        "--path" $globalWriterClaimPath `
        "--run-id" $runId `
        "--owner-pid" ([string]$PID) `
        "--ownership-token" $OwnershipToken `
        "--writer-pid" ([string]$WriterPid) 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Global writer PID attach failed: $(@($raw) -join ' ')"
    }
}

function Remove-GlobalWriterClaim {
    param(
        [Parameter(Mandatory = $true)][string]$OwnershipToken,
        [Parameter(Mandatory = $true)][string]$FinalStatus
    )

    $raw = @(& $script:python $writerClaimCli `
        "release" `
        "--path" $globalWriterClaimPath `
        "--run-id" $runId `
        "--owner-pid" ([string]$PID) `
        "--ownership-token" $OwnershipToken `
        "--final-status" $FinalStatus `
        "--archive-dir" $globalWriterClaimArchiveDir 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Global writer claim release failed: $(@($raw) -join ' ')"
    }
    return ConvertFrom-JsonPreserveDateStrings -InputJson $raw
}

function Assert-CompletedOutput {
    if (-not (Test-Path -LiteralPath $outputPath -PathType Container)) {
        throw "Runtime returned without the immutable output directory."
    }
    $files = @(Get-ChildItem -LiteralPath $outputPath -File)
    $expectedNames = @(
        "gateio-active-contracts.json",
        "manifest.json",
        "mexc-active-contracts.json",
        "provisional-shared-ticker-candidates.json"
    )
    $observedNames = @($files.Name | Sort-Object)
    if ((@($observedNames) -join "|") -ne (@($expectedNames) -join "|")) {
        throw "Immutable output file set changed."
    }
    $totalBytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
    if ($totalBytes -gt $hardOutputCapBytes) {
        throw "Immutable output exceeds the 50 MB cap."
    }
    if (@($files | Where-Object { $_.Name -match "raw" }).Count -ne 0) {
        throw "Raw payload file is forbidden."
    }
    $manifest = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath (Join-Path $outputPath "manifest.json")
    )
    $runtimeManifest = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $runtimeManifestPath
    )
    $receipt = ConvertFrom-JsonPreserveDateStrings -InputJson (
        Get-Content -Raw -LiteralPath $receiptPath
    )
    if ([string]$manifest.status -ne "COMPLETE_REQUIRES_IDENTITY_VERIFICATION") {
        throw "Immutable output status is not complete."
    }
    if ([string]$manifest.run_id -ne $runId) {
        throw "Immutable output run_id mismatch."
    }
    if ([string]$manifest.bindings.proposal_hash -ne $expectedProposalHash) {
        throw "Immutable output proposal binding mismatch."
    }
    if ([string]$manifest.bindings.receipt_hash -ne [string]$receipt.receipt_hash) {
        throw "Immutable output receipt binding mismatch."
    }
    if ([string]$manifest.bindings.runtime_manifest_hash -ne [string]$runtimeManifest.manifest_hash) {
        throw "Immutable output runtime manifest binding mismatch."
    }
    if ($manifest.raw_response_persisted -ne $false) {
        throw "Immutable output indicates a raw response was persisted."
    }
    if ($manifest.funding_rates_or_prices_persisted -ne $false) {
        throw "Immutable output indicates a market value was persisted."
    }
    return [ordered]@{
        total_bytes = $totalBytes
        contract_counts = $manifest.contract_counts
        manifest_path = Join-Path $outputPath "manifest.json"
        manifest_sha256 = Get-Sha256 -Path (Join-Path $outputPath "manifest.json")
    }
}

if ($PreflightOnly -and $VisibleWorker) {
    throw "PreflightOnly and VisibleWorker are mutually exclusive."
}

$python = Resolve-ProjectPython
$runtimeBinding = Get-RuntimeManifestBinding
$proposalPath = [string]$runtimeBinding.proposal.path
$receiptPath = [string]$runtimeBinding.approval_receipt.path
$expectedProposalFileSha256 = [string]$runtimeBinding.proposal.file_sha256
$expectedProposalHash = [string]$runtimeBinding.proposal.proposal_hash

if ($PreflightOnly) {
    Invoke-FullPreflight | ConvertTo-Json -Depth 20
    exit 0
}

if (-not $VisibleWorker) {
    $preflight = Invoke-FullPreflight
    if ([string]$preflight.status -eq "ALREADY_COMPLETE") {
        $preflight | ConvertTo-Json -Depth 20
        exit 0
    }
    if ([string]$preflight.status -eq "ALREADY_RUNNING") {
        $preflight | ConvertTo-Json -Depth 20
        exit 0
    }
    if ([string]$preflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE") {
        throw "Visible launch preflight did not authorize the single-use run."
    }

    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $childArguments = @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath,
        "-VisibleWorker"
    )
    $terminal = Start-Process `
        -FilePath $pwsh `
        -ArgumentList $childArguments `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal `
        -PassThru

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    $ownedRecord = $null
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if ($terminal.HasExited) {
            throw "Visible metadata terminal exited before claiming the exact run."
        }
        if (Test-Path -LiteralPath $launchRecordPath -PathType Leaf) {
            try {
                $candidate = ConvertFrom-JsonPreserveDateStrings -InputJson (
                    Get-Content -Raw -LiteralPath $launchRecordPath
                )
                if (
                    [string]$candidate.run_id -eq $runId -and
                    [int]$candidate.visible_terminal_pid -eq $terminal.Id
                ) {
                    $ownedRecord = $candidate
                    break
                }
            } catch {
                # The child may be between its exclusive create and first atomic update.
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ownedRecord) {
        throw "Visible metadata terminal did not claim the exact run within 30 seconds."
    }

    [ordered]@{
        schema = "trading_mvp_funding_metadata_visible_terminal_launch_v2"
        status = "VISIBLE_TERMINAL_LAUNCHED"
        run_id = $runId
        visible_terminal_pid = $terminal.Id
        terminal_ownership_verified = $true
        child_status = [string]$ownedRecord.status
        launch_record_path = $launchRecordPath
        failure_diagnostic_path = $failureDiagnosticPath
        output_path = $outputPath
        max_runtime_sec = $maxRuntimeSec
        hard_output_cap_bytes = $hardOutputCapBytes
        launched_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 10
    exit 0
}

$launchRecord = [ordered]@{
    schema = "trading_mvp_funding_metadata_discovery_launch_v2"
    status = "VISIBLE_WORKER_CLAIMED"
    run_id = $runId
    visible_terminal_pid = $PID
    terminal_ownership_verified = $true
    started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    proposal_path = $proposalPath
    proposal_file_sha256 = $expectedProposalFileSha256
    proposal_hash = $expectedProposalHash
    receipt_path = $receiptPath
    receipt_file_sha256 = Get-Sha256 -Path $receiptPath
    runtime_manifest_path = $runtimeManifestPath
    runtime_manifest_file_sha256 = Get-Sha256 -Path $runtimeManifestPath
    runtime_module_path = $runtimeModule
    runtime_module_sha256 = Get-Sha256 -Path $runtimeModule
    launcher_path = $PSCommandPath
    launcher_sha256 = Get-Sha256 -Path $PSCommandPath
    output_path = $outputPath
    failure_diagnostic_path = $failureDiagnosticPath
    failure_diagnostic_file_sha256 = $null
    runtime_failure = $null
    max_runtime_sec = $maxRuntimeSec
    hard_output_cap_bytes = $hardOutputCapBytes
    maximum_total_http_requests = 4
    allowed_endpoint_urls = $allowedEndpointUrls
    global_writer_claim_path = $globalWriterClaimPath
    writer_pid = $null
    global_writer_claim_archive_path = $null
    final_output = $null
    message = "Visible worker claimed the exact single-use run."
    retry_authorized = $false
}

$globalClaimToken = $null
$globalClaimReleased = $false
$runtimeProcess = $null
$launchRecordOwned = $false

try {
    New-LaunchRecordExclusive -Object $launchRecord
    $launchRecordOwned = $true
    Write-Host "[funding-metadata] visible exact worker claimed: $runId" -ForegroundColor Cyan

    $workerPreflight = Invoke-FullPreflight -IgnoreOwnLaunchRecord
    if ([string]$workerPreflight.status -ne "READY_FOR_VISIBLE_SINGLE_USE") {
        throw "Worker preflight did not authorize execution: $($workerPreflight.status)"
    }
    $launchRecord.guard = $workerPreflight.guard
    Set-LaunchStatus -Status "PREFLIGHT_PASSED" -Message "Fresh guard and exact hashes passed."

    $claim = New-GlobalWriterClaim
    $globalClaimToken = [string]$claim.ownership_token
    $launchRecord.global_writer_claim_acquired_at_utc = [string]$claim.claimed_at_utc
    Set-LaunchStatus -Status "GLOBAL_WRITER_CLAIMED" -Message "Single global writer claim acquired."

    $runtimeArguments = @(Get-RuntimeArguments) + @(
        "--execute",
        "--global-writer-claim-path", $globalWriterClaimPath,
        "--owner-pid", ([string]$PID),
        "--ownership-token", $globalClaimToken
    )
    $runtimeProcess = Start-Process `
        -FilePath $python `
        -ArgumentList $runtimeArguments `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -PassThru
    Set-GlobalWriterProcess -OwnershipToken $globalClaimToken -WriterPid $runtimeProcess.Id
    $launchRecord.writer_pid = $runtimeProcess.Id
    Set-LaunchStatus -Status "RUNNING" -Message "Public contract metadata request is running."
    Write-Host "[funding-metadata] running; pid=$($runtimeProcess.Id); cap=${maxRuntimeSec}s" -ForegroundColor Green

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $runtimeProcess.HasExited) {
        if ($stopwatch.Elapsed.TotalSeconds -ge $maxRuntimeSec) {
            Stop-Process -Id $runtimeProcess.Id -Force -ErrorAction SilentlyContinue
            throw "Metadata runtime exceeded the exact 300-second cap."
        }
        Write-Host ("[funding-metadata] elapsed={0:n1}s" -f $stopwatch.Elapsed.TotalSeconds)
        Start-Sleep -Seconds 2
        $runtimeProcess.Refresh()
    }
    $stopwatch.Stop()
    if ($runtimeProcess.ExitCode -ne 0) {
        $safeFailure = Read-RuntimeFailureDiagnostic
        $launchRecord.failure_diagnostic_file_sha256 = $safeFailure.file_sha256
        $launchRecord.runtime_failure = $safeFailure
        $runtimeFailureMessage = (
            "Metadata runtime failed: category={0}; stage={1}; endpoint={2}; " +
            "exit_code={3}."
        ) -f @(
            [string]$safeFailure.failure.category,
            [string]$safeFailure.failure.stage,
            [string]$safeFailure.failure.endpoint_id,
            $runtimeProcess.ExitCode
        )
        throw $runtimeFailureMessage
    }
    if (Test-Path -LiteralPath $failureDiagnosticPath -PathType Leaf) {
        throw "Runtime returned success with an unexpected failure diagnostic."
    }

    $completed = Assert-CompletedOutput
    $released = Remove-GlobalWriterClaim `
        -OwnershipToken $globalClaimToken `
        -FinalStatus "COMPLETE_METADATA_DISCOVERY"
    $globalClaimReleased = $true
    $globalClaimToken = $null
    $launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
    $launchRecord.final_output = $completed
    $launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    Set-LaunchStatus `
        -Status "COMPLETE" `
        -Message "Metadata discovery completed; identity verification remains separate."
    Write-Host "[funding-metadata] COMPLETE; identity verification is still required" -ForegroundColor Green
} catch {
    $failure = $_.Exception.Message
    if ($runtimeProcess -and -not $runtimeProcess.HasExited) {
        Stop-Process -Id $runtimeProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if (
        (Test-Path -LiteralPath $failureDiagnosticPath -PathType Leaf) -and
        -not $launchRecord.failure_diagnostic_file_sha256
    ) {
        try {
            $safeFailure = Read-RuntimeFailureDiagnostic
            $launchRecord.failure_diagnostic_file_sha256 = $safeFailure.file_sha256
            $launchRecord.runtime_failure = $safeFailure
        } catch {
            $launchRecord.runtime_failure = [ordered]@{
                status = "INVALID_FAILURE_DIAGNOSTIC_BLOCKED"
                free_form_error_persisted = $false
            }
        }
    }
    if ($globalClaimToken -and -not $globalClaimReleased) {
        try {
            $released = Remove-GlobalWriterClaim `
                -OwnershipToken $globalClaimToken `
                -FinalStatus "STOPPED_INCOMPLETE"
            $globalClaimReleased = $true
            $globalClaimToken = $null
            $launchRecord.global_writer_claim_archive_path = [string]$released.archive_path
        } catch {
            $failure += " Global writer claim release failed: $($_.Exception.Message)"
        }
    }
    if ($launchRecordOwned) {
        $launchRecord.finished_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        Set-LaunchStatus -Status "STOPPED_INCOMPLETE" -Message $failure
    }
    Write-Host "[funding-metadata] STOPPED_INCOMPLETE: $failure" -ForegroundColor Red
    throw
}
