param(
    [string]$InputPath = "",
    [string]$ManifestPath = "",
    [string]$RunLabel = "",
    [int]$TopN = 30,
    [double]$NotionalQuote = 100.0,
    [int]$FundingMinObservations = 24,
    [double]$FundingMinPositiveRatio = 0.55,
    [int]$FundingMinRegimeObservations = 24,
    [double]$FundingMinPerpVolume24hQuote = 1000000.0,
    [double]$FundingMinSpotTopNotionalQuote = 25.0,
    [double]$FundingMaxBasisStdBps = 250.0,
    [double]$FundingMaxAvgSpotSpreadBps = 30.0,
    [double]$FundingMaxAvgPerpSpreadBps = 30.0,
    [double]$FundingSpotFeeBps = 10.0,
    [double]$FundingPerpFeeBps = 7.5,
    [double]$SlippageBps = 1.0,
    [double]$FundingTargetHoldIntervals = 6.0,
    [double]$FundingMaxBreakEvenHours = 168.0,
    [string]$FundingSensitivitySpotFeeBps = "0,2.5,5,10",
    [string]$FundingSensitivityPerpFeeBps = "0,1,2.5,7.5",
    [string]$FundingSensitivitySlippageBps = "0,0.25,0.5,1",
    [string]$FundingSensitivityTargetHoldIntervals = "1,3,6,12",
    [string]$FundingSensitivityMaxBreakEvenHours = "24,72,168,336",
    [int]$FundingAcceptMinTrades = 20,
    [double]$FundingAcceptMinWinRate = 0.60,
    [double]$FundingAcceptMinExpectancyQuote = 0.0,
    [double]$FundingAcceptMinNetPnlQuote = 0.0,
    [double]$FundingAcceptMaxDrawdownQuote = 5.0,
    [double]$FundingAcceptMinProfitFactor = 1.2,
    [int]$FundingAcceptMinMarkets = 1,
    [int]$FundingAcceptMinExchanges = 1,
    [double]$FundingStressAdverseBasisBps = 25.0,
    [double]$FundingStressSpreadWidenBps = 5.0,
    [double]$FundingStressFundingFlipBps = 5.0,
    [double]$FundingStressMinNetPnlQuote = 0.0,
    [double]$FundingStressMaxDrawdownQuote = 5.0,
    [double]$FundingOosTrainFraction = 0.70,
    [int]$FundingOosMinTrainRows = 1000,
    [int]$FundingOosMinRows = 300,
    [double]$FundingOosMinTrainSpanHours = 24.0,
    [double]$FundingOosMinSpanHours = 12.0,
    [int]$FundingWalkTrainRows = 1000,
    [int]$FundingWalkTestRows = 250,
    [int]$FundingWalkStepRows = 250,
    [int]$FundingWalkMinWindows = 3,
    [int]$FundingWalkMinAcceptedWindows = 2,
    [double]$FundingWalkMinAcceptedRatio = 0.60,
    [double]$FundingWalkMinTrainSpanHours = 24.0,
    [double]$FundingWalkMinTestSpanHours = 6.0,
    [double]$FundingQualityMaxErrorRate = 0.20,
    [int]$FundingQualityMinMarkets = 10,
    [double]$FundingQualityMinAvgRowsPerCycle = 15.0,
    [int]$FundingQualityMinMinRowsPerCycle = 10,
    [string]$WatchlistPath = "",
    [switch]$AllowBlockedFundingDataset,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$runner = Join-Path $repoRoot "trading_mvp\run_mvp.ps1"
$fundingDir = Join-Path $repoRoot "exports\trading-mvp\funding"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"
$watchlistReviewScript = Join-Path $repoRoot "tools\funding_watchlist_review.ps1"
if (-not $WatchlistPath) {
    if (Test-Path -LiteralPath $gatePath) {
        try {
            $gateForWatchlist = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
            $WatchlistPath = [string]$gateForWatchlist.watchlist_path
        } catch {}
    }
}
if (-not $WatchlistPath) {
    $WatchlistPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json"
}

New-Item -ItemType Directory -Force -Path $fundingDir, $backtestDir, $runDir | Out-Null
Set-Location $repoRoot

if (-not $InputPath) {
    if (-not (Test-Path -LiteralPath $gatePath)) {
        throw "InputPath was not provided and active-run gate was not found: $gatePath"
    }
    $gate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $InputPath = [string]$gate.output_path
    if (-not $ManifestPath) {
        $ManifestPath = [string]$gate.manifest_path
    }
}

if (-not $ManifestPath) {
    $ManifestPath = $InputPath -replace "\.jsonl$", ".manifest.json"
}

$InputPath = (Resolve-Path -LiteralPath $InputPath).Path
$ManifestPath = (Resolve-Path -LiteralPath $ManifestPath).Path

$gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ($gateStatus.status -eq "RUNNING") {
    throw "Active run gate is RUNNING. Only status/ETA checks are allowed."
}
if ($gateStatus.status -eq "STOPPED_INCOMPLETE") {
    throw "Active run gate is STOPPED_INCOMPLETE. Resume or reject the incomplete collect before final review."
}
if ($gateStatus.postprocess_block -and (-not $AllowBlockedFundingDataset)) {
    $blockedManifestPath = [string]$gateStatus.manifest_path
    $blockedInputPath = ""
    if ($gateStatus.output -and $gateStatus.output.path) {
        $blockedInputPath = [string]$gateStatus.output.path
    }
    $sameBlockedManifest = $blockedManifestPath -and ((Resolve-Path -LiteralPath $blockedManifestPath).Path -eq $ManifestPath)
    $sameBlockedInput = $blockedInputPath -and ((Resolve-Path -LiteralPath $blockedInputPath).Path -eq $InputPath)
    if ($sameBlockedManifest -and $sameBlockedInput) {
        $blockedReasons = @()
        if ($gateStatus.postprocess_block.readiness_reasons) {
            $blockedReasons += @($gateStatus.postprocess_block.readiness_reasons)
        }
        if ($gateStatus.postprocess_block.data_quality_reasons) {
            $blockedReasons += @($gateStatus.postprocess_block.data_quality_reasons)
        }
        $reasonText = if ($blockedReasons.Count -gt 0) { $blockedReasons -join ", " } else { [string]$gateStatus.postprocess_block.status }
        throw "Funding dataset is blocked by guard review ($reasonText; min_rows_per_cycle=$($gateStatus.postprocess_block.min_rows_per_cycle)). Refusing funding final-review/rank/backtest/paper-forward on this dataset. Use tools/trading_next_goal_step.ps1 for the guarded WS proof path, or rerun with -AllowBlockedFundingDataset only to regenerate guard/debug evidence."
    }
}

$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$completedCycles = [int]($manifest.completed_cycles)
$totalCycles = [int]($manifest.cycles)
if (($manifest.final -ne $true) -or ($completedCycles -lt $totalCycles)) {
    throw "Funding collect is not final: final=$($manifest.final), completed_cycles=$completedCycles, cycles=$totalCycles"
}

$lineCount = (Get-Content -LiteralPath $InputPath | Measure-Object -Line).Lines
$manifestRows = [int]($manifest.rows)
if ($lineCount -ne $manifestRows) {
    throw "Line count does not match manifest rows: lines=$lineCount, manifest.rows=$manifestRows"
}

$baseName = [System.IO.Path]::GetFileNameWithoutExtension($InputPath)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$label = if ($RunLabel) { $RunLabel } else { "${baseName}_final_review_$stamp" }

$finalReviewOutput = Join-Path $fundingDir ("funding_final_review_{0}.json" -f $label)
$rankOutput = Join-Path $fundingDir ("funding_rank_{0}.json" -f $label)
$gateReportOutput = Join-Path $fundingDir ("funding_gate_report_{0}.json" -f $label)
$regimeReportOutput = Join-Path $fundingDir ("funding_regime_report_{0}.json" -f $label)
$frontierReportOutput = Join-Path $fundingDir ("funding_frontier_report_{0}.json" -f $label)
$sensitivityOutput = Join-Path $fundingDir ("funding_sensitivity_{0}.json" -f $label)
$decisionReportOutput = Join-Path $fundingDir ("funding_decision_report_{0}.json" -f $label)
$paperPlanOutput = Join-Path $fundingDir ("funding_paper_plan_{0}.json" -f $label)
$watchlistReviewOutput = Join-Path $fundingDir ("funding_watchlist_review_{0}.json" -f $label)
$watchlistReviewCsv = Join-Path $fundingDir ("funding_watchlist_review_{0}.csv" -f $label)
$watchlistPaperBlockOutput = Join-Path $fundingDir ("funding_paper_plan_watchlist_block_{0}.json" -f $label)
$backtestOutput = Join-Path $backtestDir ("funding_backtest_{0}.json" -f $label)
$oosOutput = Join-Path $backtestDir ("funding_oos_{0}.json" -f $label)
$walkForwardOutput = Join-Path $backtestDir ("funding_walk_forward_{0}.json" -f $label)
$consoleLog = Join-Path $runDir ("funding_final_review_{0}.console.log" -f $label)

$qualityMinCompletedCycles = $totalCycles
$qualityMinUniqueCycles = [Math]::Floor($totalCycles * 0.80)
$qualityMinRows = [Math]::Max(1, [Math]::Floor($totalCycles * $FundingQualityMinAvgRowsPerCycle * 0.70))

$argsList = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner,
    "-Action", "funding-final-review",
    "-InputPath", $InputPath,
    "-ManifestPath", $ManifestPath,
    "-OutputPath", $finalReviewOutput,
    "-ReportOutputPath", $rankOutput,
    "-GridOutputPath", $backtestOutput,
    "-OosOutputPath", $oosOutput,
    "-WalkForwardOutputPath", $walkForwardOutput,
    "-FundingPlanPath", $paperPlanOutput,
    "-GateReportPath", $gateReportOutput,
    "-RegimeReportPath", $regimeReportOutput,
    "-FrontierReportPath", $frontierReportOutput,
    "-SensitivityReportPath", $sensitivityOutput,
    "-DecisionReportPath", $decisionReportOutput,
    "-TopN", $TopN,
    "-NotionalQuote", $NotionalQuote,
    "-FundingMinObservations", $FundingMinObservations,
    "-FundingMinPositiveRatio", $FundingMinPositiveRatio,
    "-FundingMinRegimeObservations", $FundingMinRegimeObservations,
    "-FundingMinPerpVolume24hQuote", $FundingMinPerpVolume24hQuote,
    "-FundingMinSpotTopNotionalQuote", $FundingMinSpotTopNotionalQuote,
    "-FundingMaxBasisStdBps", $FundingMaxBasisStdBps,
    "-FundingMaxAvgSpotSpreadBps", $FundingMaxAvgSpotSpreadBps,
    "-FundingMaxAvgPerpSpreadBps", $FundingMaxAvgPerpSpreadBps,
    "-FundingSpotFeeBps", $FundingSpotFeeBps,
    "-FundingPerpFeeBps", $FundingPerpFeeBps,
    "-SlippageBps", $SlippageBps,
    "-FundingTargetHoldIntervals", $FundingTargetHoldIntervals,
    "-FundingMinRate", 0,
    "-FundingMinExpectedNetCarryBps", 0,
    "-FundingMinRiskAdjustedEdgeBps", 0,
    "-FundingMaxBreakEvenHours", $FundingMaxBreakEvenHours,
    "-FundingAcceptMinTrades", $FundingAcceptMinTrades,
    "-FundingAcceptMinWinRate", $FundingAcceptMinWinRate,
    "-FundingAcceptMinExpectancyQuote", $FundingAcceptMinExpectancyQuote,
    "-FundingAcceptMinNetPnlQuote", $FundingAcceptMinNetPnlQuote,
    "-FundingAcceptMaxDrawdownQuote", $FundingAcceptMaxDrawdownQuote,
    "-FundingAcceptMinProfitFactor", $FundingAcceptMinProfitFactor,
    "-FundingAcceptMinMarkets", $FundingAcceptMinMarkets,
    "-FundingAcceptMinExchanges", $FundingAcceptMinExchanges,
    "-FundingStress",
    "-FundingStressAdverseBasisBps", $FundingStressAdverseBasisBps,
    "-FundingStressSpreadWidenBps", $FundingStressSpreadWidenBps,
    "-FundingStressFundingFlipBps", $FundingStressFundingFlipBps,
    "-FundingStressMinNetPnlQuote", $FundingStressMinNetPnlQuote,
    "-FundingStressMaxDrawdownQuote", $FundingStressMaxDrawdownQuote,
    "-FundingSensitivitySpotFeeBps", $FundingSensitivitySpotFeeBps,
    "-FundingSensitivityPerpFeeBps", $FundingSensitivityPerpFeeBps,
    "-FundingSensitivitySlippageBps", $FundingSensitivitySlippageBps,
    "-FundingSensitivityTargetHoldIntervals", $FundingSensitivityTargetHoldIntervals,
    "-FundingSensitivityMaxBreakEvenHours", $FundingSensitivityMaxBreakEvenHours,
    "-FundingSensitivityOos",
    "-FundingSensitivityWalkForward",
    "-FundingOosTrainFraction", $FundingOosTrainFraction,
    "-FundingOosMinTrainRows", $FundingOosMinTrainRows,
    "-FundingOosMinRows", $FundingOosMinRows,
    "-FundingOosMinTrainSpanHours", $FundingOosMinTrainSpanHours,
    "-FundingOosMinSpanHours", $FundingOosMinSpanHours,
    "-FundingWalkTrainRows", $FundingWalkTrainRows,
    "-FundingWalkTestRows", $FundingWalkTestRows,
    "-FundingWalkStepRows", $FundingWalkStepRows,
    "-FundingWalkMinWindows", $FundingWalkMinWindows,
    "-FundingWalkMinAcceptedWindows", $FundingWalkMinAcceptedWindows,
    "-FundingWalkMinAcceptedRatio", $FundingWalkMinAcceptedRatio,
    "-FundingWalkMinTrainSpanHours", $FundingWalkMinTrainSpanHours,
    "-FundingWalkMinTestSpanHours", $FundingWalkMinTestSpanHours,
    "-FundingQualityMinRows", $qualityMinRows,
    "-FundingQualityMinMarkets", $FundingQualityMinMarkets,
    "-FundingQualityMinCompletedCycles", $qualityMinCompletedCycles,
    "-FundingQualityMinUniqueCycles", $qualityMinUniqueCycles,
    "-FundingQualityMinAvgRowsPerCycle", $FundingQualityMinAvgRowsPerCycle,
    "-FundingQualityMinMinRowsPerCycle", $FundingQualityMinMinRowsPerCycle,
    "-FundingQualityMaxErrorRate", $FundingQualityMaxErrorRate,
    "-FundingStrictResearch"
)

Write-Host "Starting visible funding final review"
Write-Host "Input: $InputPath"
Write-Host "Manifest: $ManifestPath"
Write-Host "Rows: $lineCount"
Write-Host "Cycles: $completedCycles/$totalCycles"
Write-Host "Final review: $finalReviewOutput"
Write-Host "Rank: $rankOutput"
Write-Host "Backtest: $backtestOutput"
Write-Host "OOS: $oosOutput"
Write-Host "Walk-forward: $walkForwardOutput"
Write-Host "Sensitivity: $sensitivityOutput"
Write-Host "Decision report: $decisionReportOutput"
Write-Host "Watchlist: $WatchlistPath"
Write-Host "Watchlist review: $watchlistReviewOutput"
Write-Host "Watchlist paper block: $watchlistPaperBlockOutput"
Write-Host "Console log: $consoleLog"

$transcriptStarted = $false
try {
    Start-Transcript -Path $consoleLog -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

try {
    & pwsh @argsList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "funding-final-review failed with exit code $exitCode"
    }
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

Write-Host "Funding final review completed"
Write-Host "Open decision report: $decisionReportOutput"

$finalReview = $null
if (Test-Path -LiteralPath $finalReviewOutput) {
    $finalReview = Get-Content -Raw -LiteralPath $finalReviewOutput | ConvertFrom-Json
}

$finalReviewStatus = if ($null -ne $finalReview) { [string]$finalReview.status } else { "" }
$finalReviewOk = if ($null -ne $finalReview) { [bool]$finalReview.ok } else { $false }
$downstreamArtifactsReady = (
    $finalReviewOk -and
    $finalReviewStatus -eq "completed" -and
    (Test-Path -LiteralPath $rankOutput) -and
    (Test-Path -LiteralPath $finalReviewOutput)
)

if (-not $downstreamArtifactsReady) {
    $reasons = @()
    if ($null -eq $finalReview) {
        $reasons += "final_review_output_missing"
    } else {
        $reasons += ("final_review_status:{0}" -f $finalReviewStatus)
        if ($null -ne $finalReview.summary -and $null -ne $finalReview.summary.reasons) {
            $reasons += @($finalReview.summary.reasons)
        }
    }
    if (-not (Test-Path -LiteralPath $rankOutput)) {
        $reasons += "rank_artifact_missing"
    }

    Write-Host "Funding final review stopped before watchlist review."
    Write-Host ("Guard reasons: {0}" -f ($reasons -join ", "))
    Write-Host "No rank artifact exists, so watchlist review is intentionally skipped."
    if (-not $NoPause) {
        Read-Host "Press Enter to close this review window"
    }
    exit 0
}

if (Test-Path -LiteralPath $watchlistReviewScript) {
    Write-Host "Running funding watchlist review"
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $watchlistReviewScript `
        -WatchlistPath $WatchlistPath `
        -RankPath $rankOutput `
        -PostprocessPath $finalReviewOutput `
        -OutputJson $watchlistReviewOutput `
        -OutputCsv $watchlistReviewCsv
    $watchlistExitCode = $LASTEXITCODE
    if ($watchlistExitCode -ne 0) {
        throw "funding_watchlist_review failed with exit code $watchlistExitCode"
    }
    Write-Host "Open watchlist review: $watchlistReviewOutput"

    $watchlistReview = Get-Content -Raw -LiteralPath $watchlistReviewOutput | ConvertFrom-Json
    $watchlistDecision = [string]$watchlistReview.decision
    $watchlistSummary = $watchlistReview.summary
    $watchlistRankEligible = 0
    $offWatchlistRankEligible = 0
    if ($null -ne $watchlistSummary.watchlist_rank_eligible) {
        $watchlistRankEligible = [int]$watchlistSummary.watchlist_rank_eligible
    }
    if ($null -ne $watchlistSummary.off_watchlist_rank_eligible) {
        $offWatchlistRankEligible = [int]$watchlistSummary.off_watchlist_rank_eligible
    }

    $watchlistSupportsPromotion = (
        $watchlistDecision -eq "WATCHLIST_SUPPORTED_ACCEPTANCE_REVIEW_REQUIRED" -and
        $watchlistRankEligible -gt 0 -and
        $offWatchlistRankEligible -eq 0
    )

    $paperPlanReady = $false
    $paperPlan = $null
    if (Test-Path -LiteralPath $paperPlanOutput) {
        $paperPlan = Get-Content -Raw -LiteralPath $paperPlanOutput | ConvertFrom-Json
        $paperPlanReady = [bool]$paperPlan.ready_for_paper_forward
    }

    $blockReasons = @()
    if (-not $watchlistSupportsPromotion) {
        $blockReasons += "watchlist_review_not_acceptance_supporting"
        $blockReasons += ("watchlist_review:{0}" -f $watchlistDecision)
    }
    if ($watchlistRankEligible -le 0) {
        $blockReasons += "watchlist_rank_eligible_zero"
    }
    if ($offWatchlistRankEligible -gt 0) {
        $blockReasons += "off_watchlist_eligible_requires_independent_review"
    }

    $backupPath = $null
    $paperPlanOverwritten = $false
    if ($paperPlanReady -and (-not $watchlistSupportsPromotion)) {
        $backupPath = $paperPlanOutput -replace "\.json$", ".pre_watchlist_review.json"
        Copy-Item -LiteralPath $paperPlanOutput -Destination $backupPath -Force

        $paperOutputPath = $paperPlanOutput -replace "\.json$", ".jsonl"
        if ($null -ne $paperPlan.paper_output_path -and [string]$paperPlan.paper_output_path) {
            $paperOutputPath = [string]$paperPlan.paper_output_path
        }

        $blockedPaperPlan = [ordered]@{
            mode = "funding_paper_forward_plan"
            ok = $false
            status = "blocked_by_watchlist_review"
            ready_for_paper_forward = $false
            research_only = $true
            live_orders = $false
            api_keys_required = $false
            leverage_enabled = $false
            margin_execution = $false
            source_postprocess = $finalReviewOutput
            source_decision_report = $decisionReportOutput
            source_watchlist_review = $watchlistReviewOutput
            original_paper_plan_backup = $backupPath
            paper_output_path = $paperOutputPath
            decision_summary = [ordered]@{
                accepted = $false
                reasons = $blockReasons
                watchlist_review_decision = $watchlistDecision
                watchlist_review_summary = $watchlistSummary
            }
            research_acceptance = [ordered]@{
                accepted = $false
                reasons = $blockReasons
            }
            research_gate_reasons = $blockReasons
            frozen_config = $null
        }
        $blockedPaperPlan | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $paperPlanOutput -Encoding UTF8
        $paperPlanOverwritten = $true
        Write-Host "Paper plan blocked by watchlist review: $paperPlanOutput"
        Write-Host "Original paper plan backup: $backupPath"
    }

    $watchlistPaperBlock = [ordered]@{
        mode = "funding_paper_plan_watchlist_block"
        ok = $true
        watchlist_supports_promotion = $watchlistSupportsPromotion
        paper_plan_ready_before_review = $paperPlanReady
        paper_plan_overwritten = $paperPlanOverwritten
        paper_plan_path = $paperPlanOutput
        original_paper_plan_backup = $backupPath
        source_watchlist_review = $watchlistReviewOutput
        watchlist_review_decision = $watchlistDecision
        watchlist_review_summary = $watchlistSummary
        block_reasons = $blockReasons
        note = if ($paperPlanReady -and (-not $watchlistSupportsPromotion)) {
            "Ready paper-forward plan was replaced with blocked_by_watchlist_review."
        } elseif (-not $paperPlanReady) {
            "No ready paper-forward plan existed to block."
        } else {
            "Watchlist review supports promotion; paper-forward still remains research-only."
        }
    }
    $watchlistPaperBlock | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $watchlistPaperBlockOutput -Encoding UTF8
    Write-Host "Open watchlist paper block: $watchlistPaperBlockOutput"
} else {
    Write-Host "Watchlist review script not found; skipped: $watchlistReviewScript"
}

if (-not $NoPause) {
    Read-Host "Press Enter to close this review window"
}
