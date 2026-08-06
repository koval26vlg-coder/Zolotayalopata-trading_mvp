param(
    [string]$PostprocessPath = "",
    [string]$ExpectedManifestPath = "",
    [string]$RunLabel = "",
    [string]$GridSignalType = "liquidity_sweep_reversal",
    [double]$NotionalQuote = 25.0,
    [switch]$PlanOnly,
    [switch]$ConfirmedResearchRun,
    [switch]$IncludeWsReplay,
    [switch]$SkipEventQuality,
    [switch]$SkipEventSlice,
    [switch]$SkipEventValidation,
    [switch]$SkipWsGrid,
    [switch]$SkipSweepGate,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$runner = Join-Path $repoRoot "trading_mvp\run_mvp.ps1"
$sweepGate = Join-Path $repoRoot "tools\sweep_reversal_acceptance_gate.ps1"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"

New-Item -ItemType Directory -Force -Path $backtestDir, $runDir | Out-Null
Set-Location $repoRoot

function Resolve-PathIfExists {
    param([string]$Path)
    if (-not $Path) {
        return ""
    }
    if (Test-Path -LiteralPath $Path) {
        return (Resolve-Path -LiteralPath $Path).Path
    }
    return [System.IO.Path]::GetFullPath($Path)
}

function Get-FileFingerprint {
    param(
        [string]$Path,
        [long]$MaxHashBytes = 1073741824
    )
    if (-not $Path) {
        return $null
    }
    $resolved = Resolve-PathIfExists -Path $Path
    if (-not (Test-Path -LiteralPath $resolved)) {
        return [ordered]@{
            path = $Path
            resolved_path = $resolved
            exists = $false
        }
    }
    $item = Get-Item -LiteralPath $resolved
    $fingerprint = [ordered]@{
        path = $Path
        resolved_path = $resolved
        exists = $true
        bytes = $item.Length
        last_write = $item.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz")
        sha256 = $null
        sha256_skipped = $false
        sha256_skip_reason = $null
        max_hash_bytes = $MaxHashBytes
    }
    if ($item.Length -le $MaxHashBytes) {
        $hash = Get-FileHash -LiteralPath $resolved -Algorithm SHA256
        $fingerprint.sha256 = $hash.Hash.ToLowerInvariant()
    } else {
        $fingerprint.sha256_skipped = $true
        $fingerprint.sha256_skip_reason = "file_too_large"
    }
    return $fingerprint
}

function New-BlockedResult {
    param(
        [string]$Reason,
        [object]$GateStatus = $null,
        [object]$Postprocess = $null,
        [string[]]$Details = @(),
        [string]$NextAction = ""
    )
    $quality = $null
    if ($null -ne $Postprocess -and $null -ne $Postprocess.data_quality) {
        $quality = $Postprocess.data_quality
    }
    return [ordered]@{
        mode = "ws_replay_validation_visible_plan"
        ok = $false
        would_run = $false
        reason = $Reason
        gate_status = if ($GateStatus) { $GateStatus.status } else { $null }
        gate_run_id = if ($GateStatus) { $GateStatus.run_id } else { $null }
        postprocess_path = $PostprocessPath
        expected_manifest_path = $ExpectedManifestPath
        postprocess_replay_allowed = if ($null -ne $Postprocess -and $null -ne $Postprocess.PSObject.Properties["replay_allowed"]) { [bool]$Postprocess.replay_allowed } else { $null }
        normalized_output = if ($null -ne $Postprocess -and $Postprocess.normalized_output) { [string]$Postprocess.normalized_output } else { $null }
        details = @($Details)
        fingerprints = [ordered]@{
            postprocess = Get-FileFingerprint -Path $PostprocessPath
            normalized = if ($null -ne $Postprocess -and $Postprocess.normalized_output) { Get-FileFingerprint -Path ([string]$Postprocess.normalized_output) } else { $null }
            quality = if ($null -ne $Postprocess -and $Postprocess.quality_output) { Get-FileFingerprint -Path ([string]$Postprocess.quality_output) } else { $null }
            manifest = if ($null -ne $Postprocess -and $Postprocess.manifest) { Get-FileFingerprint -Path ([string]$Postprocess.manifest) } else { $null }
        }
        data_quality = if ($quality) {
            [ordered]@{
                accepted = [bool]$quality.accepted
                reasons = @($quality.reasons)
                metrics = $quality.metrics
                config = $quality.config
            }
        } else {
            $null
        }
        next_action = $NextAction
        blocked_actions = @("live_orders", "api_keys", "leverage_or_margin", "paper_forward_without_accepted_research", "replay_grid_if_data_quality_rejected")
    }
}

function Assert-ExitCode {
    param(
        [int]$ExitCode,
        [string]$StepName
    )
    if ($ExitCode -ne 0) {
        throw "$StepName failed with exit code $ExitCode"
    }
}

function Assert-ExpectedOutput {
    param(
        [string]$ExpectedOutput,
        [string]$StepName,
        [datetime]$StartedAt
    )
    if (-not $ExpectedOutput) {
        return $null
    }

    $resolved = Resolve-PathIfExists -Path $ExpectedOutput
    if (-not (Test-Path -LiteralPath $resolved)) {
        throw "$StepName stage_output_missing: $resolved"
    }

    $item = Get-Item -LiteralPath $resolved
    if ($item.Length -le 0) {
        throw "$StepName stage_output_empty: $resolved"
    }

    if ($item.LastWriteTime -lt $StartedAt.AddSeconds(-5)) {
        throw "$StepName stage_output_stale: $resolved"
    }

    return [ordered]@{
        path = $resolved
        bytes = $item.Length
        last_write = $item.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz")
    }
}

function Invoke-ResearchStep {
    param(
        [string]$StepName,
        [string[]]$ArgsList,
        [string]$ExpectedOutput = ""
    )
    Write-Host ""
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $StepName) -ForegroundColor Cyan
    Write-Host ("pwsh {0}" -f ($ArgsList -join " "))
    $startedAt = Get-Date
    & pwsh @ArgsList
    Assert-ExitCode -ExitCode $LASTEXITCODE -StepName $StepName
    return (Assert-ExpectedOutput -ExpectedOutput $ExpectedOutput -StepName $StepName -StartedAt $startedAt)
}

$gateStatus = $null
if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE") {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume or reject the incomplete run before WS replay validation."
    }
}

if (-not $PostprocessPath) {
    $result = New-BlockedResult `
        -Reason "postprocess_required" `
        -GateStatus $gateStatus `
        -NextAction "Run tools\run_ws_postprocess_visible.ps1 after a completed visible WS collect, then pass -PostprocessPath <exports\trading-mvp\backtests\ws_postprocess_*.json> explicitly."
    $result | ConvertTo-Json -Depth 10
    if (-not $NoPause) {
        Read-Host "Press Enter to close this replay validation window"
    }
    exit 0
}

$PostprocessPath = (Resolve-Path -LiteralPath $PostprocessPath).Path
$ExpectedManifestPath = Resolve-PathIfExists -Path $ExpectedManifestPath
$postprocessName = [System.IO.Path]::GetFileName($PostprocessPath)
if ($postprocessName -notlike "ws_postprocess_*.json") {
    throw "PostprocessPath must point to a ws_postprocess_*.json artifact, got: $PostprocessPath"
}

if ((-not $PlanOnly) -and $ConfirmedResearchRun -and (-not $ExpectedManifestPath)) {
    $result = New-BlockedResult `
        -Reason "expected_manifest_required_for_confirmed_research_run" `
        -GateStatus $gateStatus `
        -Details @("expected_manifest=<missing>") `
        -NextAction "Re-run with -ExpectedManifestPath <completed ws_collect_*.json> so replay/grid cannot use a stale postprocess artifact."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

$postprocess = Get-Content -Raw -LiteralPath $PostprocessPath | ConvertFrom-Json
$missingFields = [System.Collections.Generic.List[string]]::new()
foreach ($fieldName in @("mode", "input", "manifest", "normalized_output", "quality_output", "data_quality")) {
    if ($null -eq $postprocess.PSObject.Properties[$fieldName] -or [string]::IsNullOrWhiteSpace([string]$postprocess.$fieldName)) {
        $missingFields.Add($fieldName) | Out-Null
    }
}
if ($null -eq $postprocess.PSObject.Properties["replay_allowed"]) {
    $missingFields.Add("replay_allowed") | Out-Null
}
if ($null -eq $postprocess.data_quality -or $null -eq $postprocess.data_quality.PSObject.Properties["accepted"]) {
    $missingFields.Add("data_quality.accepted") | Out-Null
}
if ($null -eq $postprocess.data_quality -or $null -eq $postprocess.data_quality.metrics) {
    $missingFields.Add("data_quality.metrics") | Out-Null
}
if ($null -eq $postprocess.data_quality -or $null -eq $postprocess.data_quality.config) {
    $missingFields.Add("data_quality.config") | Out-Null
}
if ($missingFields.Count -gt 0) {
    $result = New-BlockedResult `
        -Reason "invalid_postprocess_schema" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @($missingFields) `
        -NextAction "Regenerate this artifact with tools\run_ws_postprocess_visible.ps1; required fields are missing."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

$acceptedPostprocessModes = @(
    "ws_postprocess_guarded",
    "ws_market_filter_postprocess_guarded"
)
if ($acceptedPostprocessModes -notcontains [string]$postprocess.mode) {
    $result = New-BlockedResult `
        -Reason "invalid_postprocess_mode" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("mode=$($postprocess.mode)", "accepted_modes=$($acceptedPostprocessModes -join ',')") `
        -NextAction "Regenerate this artifact with tools\run_ws_postprocess_visible.ps1 or tools\run_ws_market_filter_visible.ps1."
    $result | ConvertTo-Json -Depth 10
    exit 0
}

$qualityAccepted = [bool]$postprocess.data_quality.accepted
$replayAllowed = [bool]$postprocess.replay_allowed
if ($qualityAccepted -ne $replayAllowed) {
    $result = New-BlockedResult `
        -Reason "replay_allowed_quality_mismatch" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("replay_allowed=$replayAllowed", "data_quality.accepted=$qualityAccepted") `
        -NextAction "Regenerate the WS postprocess artifact; replay_allowed must match data_quality.accepted."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

if (-not $replayAllowed) {
    $result = New-BlockedResult `
        -Reason "data_quality_rejected" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -NextAction "Reject this WS dataset or collect a cleaner visible dataset. Do not run ws-replay/ws-grid-search."
    $result | ConvertTo-Json -Depth 10
    exit 0
}

$normalizedOutput = [string]$postprocess.normalized_output
if (-not $normalizedOutput -or -not (Test-Path -LiteralPath $normalizedOutput)) {
    $result = New-BlockedResult `
        -Reason "normalized_output_missing" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -NextAction "Regenerate WS postprocess or pass the correct artifact with an existing normalized_output path."
    $result | ConvertTo-Json -Depth 10
    exit 0
}
$normalizedOutput = (Resolve-Path -LiteralPath $normalizedOutput).Path

$qualityOutput = [string]$postprocess.quality_output
if (-not $qualityOutput -or -not (Test-Path -LiteralPath $qualityOutput)) {
    $result = New-BlockedResult `
        -Reason "quality_output_missing" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -NextAction "Regenerate WS postprocess or pass the correct artifact with an existing quality_output path."
    $result | ConvertTo-Json -Depth 12
    exit 0
}
$qualityOutput = (Resolve-Path -LiteralPath $qualityOutput).Path

$manifestPath = [string]$postprocess.manifest
if (-not $manifestPath -or -not (Test-Path -LiteralPath $manifestPath)) {
    $result = New-BlockedResult `
        -Reason "manifest_missing" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -NextAction "Regenerate WS postprocess from a valid ws_collect_*.json manifest."
    $result | ConvertTo-Json -Depth 12
    exit 0
}
$manifestPath = (Resolve-Path -LiteralPath $manifestPath).Path

if ($ExpectedManifestPath -and $manifestPath -ne $ExpectedManifestPath) {
    $result = New-BlockedResult `
        -Reason "expected_manifest_mismatch" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("artifact_manifest=$manifestPath", "expected_manifest=$ExpectedManifestPath") `
        -NextAction "Use the postprocess artifact generated from the expected completed WS manifest."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

$qualityInput = Resolve-PathIfExists -Path ([string]$postprocess.data_quality.input)
if ($qualityInput -and $qualityInput -ne $normalizedOutput) {
    $result = New-BlockedResult `
        -Reason "quality_input_mismatch" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("data_quality.input=$qualityInput", "normalized_output=$normalizedOutput") `
        -NextAction "Regenerate WS postprocess; quality input must match normalized_output."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

$qualityManifest = Resolve-PathIfExists -Path ([string]$postprocess.data_quality.manifest)
if ($qualityManifest -and $qualityManifest -ne $manifestPath) {
    $result = New-BlockedResult `
        -Reason "quality_manifest_mismatch" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("data_quality.manifest=$qualityManifest", "manifest=$manifestPath") `
        -NextAction "Regenerate WS postprocess; quality manifest must match postprocess manifest."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

$qualityArtifact = Get-Content -Raw -LiteralPath $qualityOutput | ConvertFrom-Json
if ([string]$qualityArtifact.mode -ne "ws_data_quality") {
    $result = New-BlockedResult `
        -Reason "invalid_quality_artifact_mode" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("quality_output.mode=$($qualityArtifact.mode)") `
        -NextAction "Regenerate WS postprocess; quality_output must point to a ws_data_quality artifact."
    $result | ConvertTo-Json -Depth 12
    exit 0
}
if ([bool]$qualityArtifact.accepted -ne $qualityAccepted) {
    $result = New-BlockedResult `
        -Reason "quality_artifact_acceptance_mismatch" `
        -GateStatus $gateStatus `
        -Postprocess $postprocess `
        -Details @("embedded_data_quality.accepted=$qualityAccepted", "quality_output.accepted=$([bool]$qualityArtifact.accepted)") `
        -NextAction "Regenerate WS postprocess; embedded and file-backed data quality must match."
    $result | ConvertTo-Json -Depth 12
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$postprocessStem = [System.IO.Path]::GetFileNameWithoutExtension($PostprocessPath)
$label = if ($RunLabel) { $RunLabel } else { "${postprocessStem}_replay_validation_$stamp" }

$eventQualityOutput = Join-Path $backtestDir ("event_quality_{0}.json" -f $label)
$eventSliceOutput = Join-Path $backtestDir ("event_slice_optimizer_{0}.json" -f $label)
$eventValidationOutput = Join-Path $backtestDir ("event_validation_{0}.json" -f $label)
$wsReplayOutput = Join-Path $backtestDir ("ws_replay_{0}.json" -f $label)
$wsGridOutput = Join-Path $backtestDir ("ws_grid_search_{0}.json" -f $label)
$sweepGateOutput = Join-Path $backtestDir ("sweep_reversal_acceptance_{0}.json" -f $label)
$validationOutput = Join-Path $backtestDir ("ws_replay_validation_{0}.json" -f $label)
$consoleLog = Join-Path $runDir ("ws_replay_validation_{0}.console.log" -f $label)

$commonReplayArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner,
    "-InputPath", $normalizedOutput,
    "-NotionalQuote", ([string]$NotionalQuote),
    "-ExecutionMode", "maker",
    "-MakerFeeBps", "0",
    "-TakerFeeBps", "10",
    "-SlippageBps", "0",
    "-LatencyMs", "250",
    "-FlowWindowSec", "5",
    "-MakerQueueModel", "top_qty_fraction",
    "-MakerQueueAheadFraction", "1",
    "-MakerOrderTtlSec", "5",
    "-QualityFilter",
    "-QualityWindowSec", "60",
    "-QualityMinTradeCount", "20",
    "-QualityMinTradeNotional", "1000",
    "-QualityMaxAvgSpreadBps", "6",
    "-QualityMinQuoteUpdates", "10",
    "-MinNetTakeProfitBps", "1"
)

$effectiveSkipWsGrid = [bool]$SkipWsGrid
$effectiveSkipSweepGate = [bool]$SkipSweepGate -or $effectiveSkipWsGrid

$commands = [ordered]@{
    event_quality = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner, "-Action", "event-quality-report", "-InputPath", $normalizedOutput, "-OutputPath", $eventQualityOutput)
    event_slice = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner, "-Action", "event-slice-optimizer", "-InputPath", $eventQualityOutput, "-OutputPath", $eventSliceOutput)
    event_validation = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner, "-Action", "event-validation-report", "-InputPath", $eventQualityOutput, "-OutputPath", $eventValidationOutput)
    ws_replay = if ($IncludeWsReplay) { $commonReplayArgs + @("-Action", "ws-replay", "-SignalType", "liquidity_sweep_reversal", "-OutputPath", $wsReplayOutput) } else { $null }
    ws_grid = if (-not $effectiveSkipWsGrid) { $commonReplayArgs + @(
        "-Action", "ws-grid-search",
        "-GridSignalType", $GridSignalType,
        "-GridImbalance", "0.05,0.1",
        "-GridFlow", "250,1000,2500",
        "-GridSpread", "3,6",
        "-GridTakeProfit", "6,10",
        "-GridStopLoss", "3,6",
        "-GridMaxHoldSec", "15,25",
        "-MinTrades", "20",
        "-MinWinRate", "0.6",
        "-MinExpectancyQuote", "0",
        "-MinNetPnlQuote", "0",
        "-MinProfitFactor", "1.2",
        "-MaxDrawdownQuote", "5",
        "-TopN", "30",
        "-OutputPath", $wsGridOutput
    ) } else { $null }
    sweep_gate = if (-not $effectiveSkipSweepGate) { @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $sweepGate,
        "-EventQualityPath", $eventQualityOutput,
        "-EventValidationPath", $eventValidationOutput,
        "-WsGridPath", $wsGridOutput,
        "-OutputPath", $sweepGateOutput
    ) } else { $null }
}

$plan = [ordered]@{
    mode = "ws_replay_validation_visible_plan"
    ok = $true
    would_run = (-not [bool]$PlanOnly)
    confirmed_research_run = [bool]$ConfirmedResearchRun
    postprocess_path = $PostprocessPath
    expected_manifest_path = $ExpectedManifestPath
    postprocess_replay_allowed = $replayAllowed
    normalized_output = $normalizedOutput
    quality_output = $qualityOutput
    manifest = $manifestPath
    run_label = $label
    fingerprints = [ordered]@{
        postprocess = Get-FileFingerprint -Path $PostprocessPath
        normalized = Get-FileFingerprint -Path $normalizedOutput
        quality = Get-FileFingerprint -Path $qualityOutput
        manifest = Get-FileFingerprint -Path $manifestPath
    }
    outputs = [ordered]@{
        event_quality = $eventQualityOutput
        event_slice = $eventSliceOutput
        event_validation = $eventValidationOutput
        ws_replay = if ($IncludeWsReplay) { $wsReplayOutput } else { $null }
        ws_grid = if (-not $effectiveSkipWsGrid) { $wsGridOutput } else { $null }
        sweep_gate = if (-not $effectiveSkipSweepGate) { $sweepGateOutput } else { $null }
        validation_summary = $validationOutput
        console_log = $consoleLog
    }
    commands = $commands
    skipped_by_options = [ordered]@{
        event_quality = [bool]$SkipEventQuality
        event_slice = [bool]$SkipEventSlice
        event_validation = [bool]$SkipEventValidation
        ws_replay = (-not [bool]$IncludeWsReplay)
        ws_grid = $effectiveSkipWsGrid
        sweep_gate = $effectiveSkipSweepGate
    }
    skip_reasons = [ordered]@{
        ws_replay = if (-not [bool]$IncludeWsReplay) { "IncludeWsReplay_not_set" } else { $null }
        ws_grid = if ($effectiveSkipWsGrid) { "SkipWsGrid" } else { $null }
        sweep_gate = if ([bool]$SkipSweepGate) { "SkipSweepGate" } elseif ($effectiveSkipWsGrid) { "requires_ws_grid" } else { $null }
    }
    data_quality = [ordered]@{
        accepted = [bool]$postprocess.data_quality.accepted
        reasons = @($postprocess.data_quality.reasons)
        metrics = $postprocess.data_quality.metrics
        config = $postprocess.data_quality.config
    }
    blocked_actions = @("live_orders", "api_keys", "leverage_or_margin", "paper_forward_without_accepted_research", "replay_grid_if_data_quality_rejected")
    next_after_replay_validation = "Run sweep_reversal_acceptance_gate and strategy_acceptance_gate. Paper-forward remains blocked unless research gates pass on independent data."
}

if ($PlanOnly) {
    $plan["would_run"] = $false
    $plan | ConvertTo-Json -Depth 12
    exit 0
}

if (-not $ConfirmedResearchRun) {
    $plan["ok"] = $false
    $plan["would_run"] = $false
    $plan["reason"] = "confirmed_research_run_required"
    $plan["next_action"] = "Re-run with -ConfirmedResearchRun only after reviewing this plan. This still remains research-only and does not enable paper/live."
    $plan | ConvertTo-Json -Depth 12
    if (-not $NoPause) {
        Read-Host "Press Enter to close this replay validation window"
    }
    exit 0
}

Write-Host "Starting visible guarded WS replay validation"
Write-Host "Postprocess: $PostprocessPath"
Write-Host "Normalized: $normalizedOutput"
Write-Host "Validation summary: $validationOutput"
Write-Host "Console log: $consoleLog"

$transcriptStarted = $false
try {
    Start-Transcript -Path $consoleLog -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

$stageResults = [System.Collections.Generic.List[object]]::new()
try {
    if (-not $SkipEventQuality) {
        $outputCheck = Invoke-ResearchStep -StepName "event-quality-report" -ArgsList $commands.event_quality -ExpectedOutput $eventQualityOutput
        $stageResults.Add([ordered]@{ stage = "event_quality"; output = $eventQualityOutput; output_check = $outputCheck; status = "completed" }) | Out-Null
    }
    if (-not $SkipEventSlice) {
        $outputCheck = Invoke-ResearchStep -StepName "event-slice-optimizer" -ArgsList $commands.event_slice -ExpectedOutput $eventSliceOutput
        $stageResults.Add([ordered]@{ stage = "event_slice"; output = $eventSliceOutput; output_check = $outputCheck; status = "completed" }) | Out-Null
    }
    if (-not $SkipEventValidation) {
        $outputCheck = Invoke-ResearchStep -StepName "event-validation-report" -ArgsList $commands.event_validation -ExpectedOutput $eventValidationOutput
        $stageResults.Add([ordered]@{ stage = "event_validation"; output = $eventValidationOutput; output_check = $outputCheck; status = "completed" }) | Out-Null
    }
    if ($IncludeWsReplay) {
        $outputCheck = Invoke-ResearchStep -StepName "ws-replay" -ArgsList $commands.ws_replay -ExpectedOutput $wsReplayOutput
        $stageResults.Add([ordered]@{ stage = "ws_replay"; output = $wsReplayOutput; output_check = $outputCheck; status = "completed" }) | Out-Null
    }
    if (-not $effectiveSkipWsGrid) {
        $outputCheck = Invoke-ResearchStep -StepName "ws-grid-search" -ArgsList $commands.ws_grid -ExpectedOutput $wsGridOutput
        $stageResults.Add([ordered]@{ stage = "ws_grid"; output = $wsGridOutput; output_check = $outputCheck; status = "completed" }) | Out-Null
    }
    if (-not $effectiveSkipSweepGate) {
        $outputCheck = Invoke-ResearchStep -StepName "sweep-reversal-acceptance-gate" -ArgsList $commands.sweep_gate -ExpectedOutput $sweepGateOutput
        $stageResults.Add([ordered]@{ stage = "sweep_gate"; output = $sweepGateOutput; output_check = $outputCheck; status = "completed" }) | Out-Null
    }
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

$summary = [ordered]@{
    mode = "ws_replay_validation_visible"
    ok = $true
    completed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    postprocess_path = $PostprocessPath
    normalized_output = $normalizedOutput
    quality_output = $qualityOutput
    manifest = $manifestPath
    fingerprints = $plan.fingerprints
    stages = @($stageResults)
    outputs = $plan.outputs
    blocked_actions = $plan.blocked_actions
    next_after_replay_validation = $plan.next_after_replay_validation
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $validationOutput -Encoding UTF8
$summary | ConvertTo-Json -Depth 12

if (-not $NoPause) {
    Read-Host "Press Enter to close this replay validation window"
}
