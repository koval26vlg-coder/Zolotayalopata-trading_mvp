param(
    [string]$Config = "",
    [ValidateSet("universe","collect","backtest","run","multi-run","ws-collect","ws-normalize","ws-data-quality","ws-postprocess","perp-collect","perp-report","event-quality-report","event-slice-optimizer","event-validation-report","cross-venue-dislocation","perp-postprocess","ws-replay","ws-grid-search","perp-replay","perp-grid-search","funding-scan","funding-coverage","funding-collect","funding-status","funding-collect-diagnostics","funding-wait-ready","funding-rank","funding-gate-report","funding-regime-report","funding-frontier-report","funding-decision-report","funding-progress-report","funding-backtest","funding-sensitivity","funding-oos-backtest","funding-walk-forward","funding-postprocess","funding-finalize","funding-final-review","funding-paper-plan","funding-paper-forward","funding-paper-decision-report","funding-goal-audit","resolve-active-run","fast-edge-membership-plan","fast-edge-membership-probe","fast-edge-membership-v2-plan","fast-edge-membership-v2-probe","fast-edge-membership-v3-source-plan","fast-edge-membership-v3-source-probe","fast-edge-membership-v3-history-plan","fast-edge-membership-v3-history-collect","fast-edge-membership-v3-history-quality-plan","fast-edge-membership-v3-history-quality","fast-edge-membership-history-plan","fast-edge-membership-history-collect","fast-edge-membership-history-quality","fast-edge-membership-momentum-train-plan","fast-edge-membership-momentum-train","fast-edge-membership-momentum-v2-train-plan","fast-edge-membership-momentum-v2-train","fast-edge-membership-momentum-v2-oos-plan","fast-edge-membership-momentum-v2-oos","fast-edge-membership-momentum-v2-execution-probe-plan","fast-edge-membership-momentum-v2-execution-probe-validate","fast-edge-membership-momentum-v2-market-snapshot-plan","fast-edge-membership-momentum-v2-market-snapshot-collect","fast-edge-membership-momentum-v2-execution-selection","fast-edge-membership-momentum-v2-execution-selection-validate","fast-edge-membership-momentum-v2-execution-probe-window-plan","fast-edge-membership-momentum-v2-execution-probe-collect","fast-edge-membership-momentum-v2-execution-probe-evaluate","fast-edge-membership-momentum-v2-paper-plan","fast-edge-membership-momentum-v2-paper-validate","fast-edge-membership-momentum-v2-paper-approve","fast-edge-membership-momentum-v2-paper-init","fast-edge-membership-momentum-v2-paper-execution-window-plan","fast-edge-membership-momentum-v2-paper-execution-raw","fast-edge-membership-momentum-v2-paper-funding-raw","fast-edge-membership-momentum-v2-paper-source","fast-edge-membership-momentum-v2-paper-evidence","fast-edge-membership-momentum-v2-paper-event","fast-edge-membership-momentum-v2-paper-apply","fast-edge-membership-momentum-v2-paper-status","fast-edge-membership-momentum-v2-paper-incident","fast-edge-membership-momentum-oos-plan","fast-edge-membership-momentum-oos","fast-edge-plan","fast-edge-evaluate","fast-edge-basis-universe-build","fast-edge-basis-plan","fast-edge-basis-history-collect","fast-edge-basis-history-quality","fast-edge-basis-evaluate","fast-edge-basis-probe-plan","fast-edge-basis-probe","fast-edge-basis-report","fast-edge-basis-paper-init","fast-edge-basis-paper-observe","fast-edge-basis-paper-status","fast-edge-basis-v2-preflight","fast-edge-basis-v2-plan","fast-edge-basis-v2-cache-audit","fast-edge-basis-v2-history-collect","fast-edge-basis-v2-history-quality","fast-edge-basis-v2-train-postprocess","fast-edge-basis-v2-oos-postprocess","fast-edge-basis-v2-evaluate","fast-edge-basis-v2-report","fast-edge-basis-v2-execution-probe-plan","fast-edge-basis-v2-execution-probe","fast-edge-basis-v2-execution-probe-evaluate","fast-edge-basis-v2-paper-plan","fast-edge-basis-v2-paper-init","fast-edge-basis-v2-paper-observe","fast-edge-basis-v2-paper-status","fast-edge-basis-v2-paper-observer-fixture-plan","fast-edge-basis-v2-paper-observer-fixture-run","fast-edge-basis-v2-paper-observer-fixture-sink","fast-edge-funding-persistence-v2-plan","fast-edge-funding-persistence-v2-validate","fast-edge-funding-persistence-v2-train-feasibility","fast-edge-funding-persistence-v2-oos","fast-edge-v2-validate","fast-edge-v2-evaluate","fast-edge-v3-validate","fast-edge-v3-evaluate","fast-edge-v4-validate","fast-edge-v4-evaluate","fast-edge-v5-validate","fast-edge-v5-evaluate","fast-edge-v6-validate","fast-edge-v6-evaluate","fast-edge-data-track-plan","fast-edge-night-schedule-plan","fast-edge-night-schedule-status","fast-edge-night-schedule-quality","fast-edge-pit-futility-plan","fast-edge-pit-futility-evaluate","fast-edge-pit-input-plan","fast-edge-pit-feasibility","fast-edge-pit-evaluate","fast-edge-pit-execution-probe-plan","fast-edge-pit-execution-probe-evaluate","fast-edge-pit-paper-plan","fast-edge-pit-paper-evaluate","fast-edge-feasibility","fast-edge-execution-probe","fast-edge-report","paper-forward-segment","setup-registry","experiment-record","experiment-list")]
    [string]$Action = "run",
    [ValidateSet("paper")]
    [string]$Mode = "paper",
    [int]$Seconds = 60,
    [int]$Cycles = 120,
    [string]$Exchanges = "mexc,gateio,kucoin,bingx",
    [int]$MaxPairsPerExchange = 5,
    [int]$MaxSymbols = 200,
    [string]$Quote = "USDT",
    [double]$PaperNotionalQuote = 25.0,
    [int]$DurationSec = 0,
    [ValidateSet("100ms","10ms")]
    [string]$UpdateInterval = "100ms",
    [int]$DepthLimit = 20,
    [int]$TradesLimit = 50,
    [string]$InputPath = "",
    [string]$OutputPath = "",
    [string]$MatchedUniverseOutputPath = "",
    [string]$QualityUniverseOutputPath = "",
    [string]$ManifestPath = "",
    [string]$ReportOutputPath = "",
    [string]$GridOutputPath = "",
    [string]$OosOutputPath = "",
    [string]$WalkForwardOutputPath = "",
    [string]$PaperOutputPath = "",
    [string]$PaperSummaryOutputPath = "",
    [string]$FundingPlanPath = "",
    [string]$GateReportPath = "",
    [string]$RegimeReportPath = "",
    [string]$FrontierReportPath = "",
    [string]$SensitivityReportPath = "",
    [string]$PostprocessReportPath = "",
    [string]$DecisionReportPath = "",
    [switch]$AllowPartial,
    [string]$SignalType = "flow_continue",
    [double]$NotionalQuote = 25.0,
    [ValidateSet("taker","maker")]
    [string]$ExecutionMode = "taker",
    [double]$TakerFeeBps = 10.0,
    [double]$MakerFeeBps = 0.0,
    [double]$SlippageBps = 1.0,
    [string]$VenueCostsJson = "",
    [double]$MaxQuoteAgeSec = 2.0,
    [int]$LatencyMs = 250,
    [double]$FlowWindowSec = 5.0,
    [switch]$AllowShort,
    [int]$MaxOpenPositions = 1,
    [double]$MakerQueueAheadQty = 0.0,
    [ValidateSet("fixed","top_qty_fraction")]
    [string]$MakerQueueModel = "fixed",
    [double]$MakerQueueAheadFraction = 1.0,
    [double]$MakerOrderTtlSec = 5.0,
    [switch]$QualityFilter,
    [double]$QualityWindowSec = 60.0,
    [int]$QualityMinTradeCount = 0,
    [double]$QualityMinTradeNotional = 0.0,
    [double]$QualityMaxAvgSpreadBps = 0.0,
    [int]$QualityMinQuoteUpdates = 0,
    [double]$QualityMinTopQty = 0.0,
    [double]$MinNetTakeProfitBps = -1000000000.0,
    [string]$SweepV2AllowedMarkets = "",
    [string]$SweepV2Side = "",
    [double]$SweepV2MinTradeNotionalQuote = 0.0,
    [double]$SweepV2MinIntensityBps = 0.0,
    [double]$SweepV2MaxPreSpreadBps = 0.0,
    [double]$SweepV2MaxReclaimSec = 0.0,
    [double]$SweepV2EventCooldownSec = 0.0,
    [string]$GridSignalType = "flow_continue",
    [string]$GridImbalance = "0.1,0.25",
    [string]$GridFlow = "50,250,1000",
    [string]$GridSpread = "1.5,3",
    [string]$GridTakeProfit = "3,6",
    [string]$GridStopLoss = "3,6",
    [string]$GridMaxHoldSec = "5,25",
    [int]$MinTrades = 1,
    [double]$MinWinRate = 0.0,
    [double]$MinExpectancyQuote = -1000000000.0,
    [double]$MinNetPnlQuote = -1000000000.0,
    [double]$MinProfitFactor = 0.0,
    [double]$MaxDrawdownQuote = 0.0,
    [int]$TopN = 20,
    [int]$MaxGridCombinations = 10000,
    [double]$FundingMaxSpotSpreadBps = 30.0,
    [double]$FundingMaxPerpSpreadBps = 30.0,
    [double]$FundingMaxAbsBasisBps = 500.0,
    [double]$FundingMinBasisBps = -1000000000.0,
    [double]$FundingMinRate = 0.0,
    [double]$FundingMinVolume24hQuote = 0.0,
    [double]$FundingSpotFeeBps = 10.0,
    [double]$FundingPerpFeeBps = 7.5,
    [double]$FundingMinTotalScore = 0.0,
    [double]$FundingTargetHoldIntervals = 1.0,
    [double]$FundingMinExpectedNetCarryBps = -1000000000.0,
    [double]$FundingMinRiskAdjustedEdgeBps = -1000000000.0,
    [double]$FundingBasisRiskMultiplier = 1.0,
    [double]$FundingSpreadRiskMultiplier = 1.0,
    [double]$FundingMaxBreakEvenHours = 1000000000.0,
    [string]$FundingSensitivitySpotFeeBps = "0,5,10",
    [string]$FundingSensitivityPerpFeeBps = "0,2.5,7.5",
    [string]$FundingSensitivitySlippageBps = "0,0.5,1",
    [string]$FundingSensitivityTargetHoldIntervals = "1,3,6",
    [string]$FundingSensitivityMaxBreakEvenHours = "24,72,168",
    [switch]$FundingSensitivityOos,
    [switch]$FundingSensitivityWalkForward,
    [int]$FundingMinObservations = 1,
    [double]$FundingMinPositiveRatio = 0.0,
    [double]$FundingMinPersistenceScore = -1000000000.0,
    [double]$FundingPersistenceWeight = 1.0,
    [int]$FundingMinRegimeObservations = 1,
    [double]$FundingMinPerpVolume24hQuote = 0.0,
    [double]$FundingMinSpotTopNotionalQuote = 0.0,
    [double]$FundingMaxBasisStdBps = 1000000000.0,
    [double]$FundingMaxAvgSpotSpreadBps = 1000000000.0,
    [double]$FundingMaxAvgPerpSpreadBps = 1000000000.0,
    [switch]$FundingResume,
    [int]$FundingAcceptMinTrades = 20,
    [double]$FundingAcceptMinWinRate = 0.60,
    [double]$FundingAcceptMinExpectancyQuote = 0.0,
    [double]$FundingAcceptMinNetPnlQuote = 0.0,
    [double]$FundingAcceptMaxDrawdownQuote = 5.0,
    [double]$FundingAcceptMinProfitFactor = 1.2,
    [int]$FundingAcceptMinMarkets = 1,
    [double]$FundingAcceptMaxMarketTradeShare = 1.0,
    [int]$FundingAcceptMinExchanges = 1,
    [double]$FundingAcceptMaxExchangeTradeShare = 1.0,
    [int]$FundingAcceptMinProfitableWindows = 0,
    [double]$FundingAcceptMaxWindowPnlShare = 1.0,
    [int]$FundingQualityMinRows = 1,
    [int]$FundingQualityMinMarkets = 1,
    [int]$FundingQualityMinCompletedCycles = 1,
    [int]$FundingQualityMinUniqueCycles = 0,
    [double]$FundingQualityMinAvgRowsPerCycle = 0.0,
    [int]$FundingQualityMinMinRowsPerCycle = 0,
    [double]$FundingQualityMaxErrorRate = 1.0,
    [double]$FundingQualityMaxCycleMarketDuplicateRate = 1.0,
    [string]$FundingQualityRequiredRowFields = "",
    [double]$FundingQualityMinRequiredRowFieldPresence = 1.0,
    [switch]$FundingStrictResearch,
    [switch]$FundingStress,
    [double]$FundingStressAdverseBasisBps = 0.0,
    [double]$FundingStressSpreadWidenBps = 0.0,
    [double]$FundingStressFundingFlipBps = 0.0,
    [double]$FundingStressMinNetPnlQuote = 0.0,
    [double]$FundingStressMaxDrawdownQuote = 5.0,
    [double]$FundingStatusStaleAfterSec = 900.0,
    [double]$FundingOosTrainFraction = 0.70,
    [int]$FundingOosMinTrainRows = 20,
    [int]$FundingOosMinRows = 20,
    [double]$FundingOosMinTrainSpanHours = 0.0,
    [double]$FundingOosMinSpanHours = 0.0,
    [int]$FundingWalkTrainRows = 200,
    [int]$FundingWalkTestRows = 50,
    [int]$FundingWalkStepRows = 50,
    [int]$FundingWalkMinWindows = 3,
    [int]$FundingWalkMinAcceptedWindows = 3,
    [double]$FundingWalkMinAcceptedRatio = 1.0,
    [double]$FundingWalkMinTrainSpanHours = 0.0,
    [double]$FundingWalkMinTestSpanHours = 0.0,
    [double]$FundingPaperMinForwardHours = 24.0,
    [int]$FundingPaperMinForwardRows = 20,
    [int]$FundingPaperMinForwardMarkets = 1,
    [switch]$FundingAllowSourceInput,
    [double]$PollIntervalSec = 60.0,
    [double]$EventLookbackSec = 120.0,
    [double]$EventHorizonSec = 300.0,
    [double]$EventMinSweepNotionalQuote = 1000.0,
    [double]$EventReclaimBps = 0.0,
    [double]$EventTargetBps = 6.0,
    [double]$EventStopBps = 3.0,
    [double]$EventMaxPreSpreadBps = 0.0,
    [double]$EventCooldownSec = 10.0,
    [int]$EventMaxEvents = 5000,
    [double]$CrossVenueStaleQuoteSec = 2.0,
    [double]$CrossVenueMinTopNotionalQuote = 25.0,
    [double]$CrossVenueRoundTripFeeBps = 39.0,
    [double]$CrossVenueSlippageBps = 10.0,
    [double]$CrossVenueInventoryRebalanceBufferBps = 20.0,
    [double]$CrossVenueMinNetEdgeBps = 0.0,
    [double]$CrossVenueCooldownSec = 60.0,
    [int]$CrossVenueMaxRows = 0,
    [int]$CrossVenueMaxEvents = 1000,
    [int]$CrossVenueProgressEveryRows = 0,
    [string]$CrossVenueIncludeBases = "",
    [int]$SliceMinEvents = 20,
    [int]$SliceMinReclaimed = 10,
    [double]$SliceMinTargetBeforeStopRate = 0.60,
    [double]$SliceMinTargetRateAll = 0.20,
    [double]$SliceMaxFalseSweepRate = 1.0,
    [double]$SliceMaxAvgAdverseBps = 0.0,
    [double]$SliceMinFavorableToAdverse = 0.0,
    [string]$SliceMinSweepIntensityBps = "0,2,5,10",
    [string]$SliceMaxTimeToReclaimSec = "0,30,60,120,300",
    [string]$SliceMaxPreSpreadBps = "0,1,3,6",
    [string]$SliceMaxAbsBasisBps = "0,5,10,25,100",
    [string]$SliceMinTradeNotionalQuote = "0,2500,5000,10000",
    [double]$ValidationTrainFraction = 0.70,
    [int]$ValidationWalkForwardWindows = 4,
    [double]$ValidationWalkForwardMinPassRatio = 0.75,
    [double]$ValidationMaxFalseSweepRate = 0.50,
    [double]$ValidationMinFavorableToAdverse = 1.0,
    [double]$ValidationStressFavorableHaircutBps = 1.0,
    [double]$ValidationStressAdverseWidenBps = 1.0,
    [double]$ValidationStressTargetBps = 6.0,
    [double]$ValidationStressStopBps = 3.0,
    [int]$WsQualityMinRows = 1,
    [int]$WsQualityMinExchanges = 1,
    [int]$WsQualityMinMarkets = 1,
    [double]$WsQualityMinSpanHours = 0.0,
    [double]$WsQualityMinDurationRatio = 0.0,
    [double]$WsQualityMaxParseErrorRate = 1.0,
    [string]$WsQualityRequiredEventKinds = "bbo,depth,trade",
    [int]$WsQualityMinMarketsWithRequiredKinds = 0,
    [double]$WsQualityMaxMarketEventShare = 1.0,
    [double]$WsQualityMaxGapSec = 0.0,
    [int]$WsQualityMaxManifestErrorCount = 1000000,
    [string]$SourceVideoId = "",
    [string]$SourceUrl = "",
    [string]$SourceChannel = "https://www.youtube.com/@AnufrievNikita/",
    [string]$Participant = "",
    [string]$ClaimFamily = "",
    [string]$Hypothesis = "",
    [string]$SetupId = "",
    [string]$Dataset = "",
    [string]$ConfigJson = "",
    [string]$ResultPath = "",
    [string]$MetricsJson = "",
    [ValidateSet("untested","failed","inconclusive","promising","accepted_research","rejected","blocked")]
    [string]$Verdict = "untested",
    [string]$VerdictReason = "",
    [string]$Tags = "",
    [string]$Notes = "",
    [string]$FeeScheduleRevision = "unspecified",
    [string]$EvaluationScope = "unspecified",
    [string]$OosStatus = "not_evaluated",
    [string]$HypothesisBankPath = "",
    [string]$GoalPath = "",
    [string]$DataType = "",
    [string]$InputMerkleSha256 = "",
    [string]$TrackId = "",
    [int]$TrainCandidateEvents = 0,
    [int]$TrainValidEvents = 0,
    [int]$OosCandidateEvents = 0,
    [string]$PerVenueOosCandidateEventsJson = "",
    [int]$UniqueOosDates = 0,
    [double]$DualVenueCoverage = 0.0,
    [double]$CapacityProxyQuotePerSelectedLeg = 0.0,
    [string]$ScheduleStartDate = "",
    [ValidateRange(1, 14)]
    [int]$ScheduleNights = 14,
    [string]$ScheduleStartLocal = "23:00",
    [ValidateSet("train_accrual", "oos_accrual")]
    [string]$ScheduleCollectionStage = "train_accrual",
    [ValidateRange(1, 10800)]
    [int]$ScheduleSegmentDurationSec = 1200,
    [ValidateRange(1, 10800)]
    [int]$ScheduleIntervalSec = 300,
    [string]$ScheduleOutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2",
    [ValidateRange(1, 10800)]
    [int]$MaxRuntimeSec = 1200,
    [long]$NotBeforeDay = 0,
    [ValidateRange(1, 20)]
    [int]$ShortlistLimit = 20,
    [double]$FastEdgeNotionalPerLeg = 1000.0,
    [double]$IntervalSec = 5.0,
    [string]$PlanPath = "",
    [string]$CoinRegistryPath = "",
    [string]$BasisCodeSnapshotRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis\code-snapshots",
    [ValidateSet("train_feasibility", "full_evaluation")]
    [string]$PitPlanStage = "train_feasibility",
    [string]$TrainPlanPath = "",
    [string]$ExpectedPlanHash = "",
    [string]$ExpectedArtifactHash = "",
    [string]$ExpectedEvidenceHash = "",
    [string]$ExpectedRawManifestHash = "",
    [string]$EntrySourcePath = "",
    [string]$ExpectedEntrySourceHash = "",
    [string]$ExitSourcePath = "",
    [string]$ExpectedExitSourceHash = "",
    [string]$FundingHistoryPaths = "",
    [ValidateSet("entry", "exit")]
    [string]$PaperBoundary = "entry",
    [string]$QualityReportPath = "",
    [string]$FundingOutputPath = "",
    [string]$ProbePlanPath = "",
    [string]$ProbeManifestPaths = "",
    [string]$SamplesPath = "",
    [string]$WindowManifestPath = "",
    [string]$FirstProbeWindowStartUtc = "",
    [ValidateRange(0, 2)]
    [int]$WindowIndex = 0,
    [ValidateRange(1, 8)]
    [int]$ProbeWorkers = 4,
    [string]$ParallelParentRunId = "",
    [string]$ApprovalRecordRoot = "",
    [string]$PaperApprovalPath = "",
    [string]$QualityLedgerPath = "",
    [string]$EvaluationPath = "",
    [string]$ClosurePath = "",
    [string]$FeasibilityPath = "",
    [string]$ExpectedFeasibilityResultHash = "",
    [string]$ExecutionProbePath = "",
    [string]$FastEdgeReportPath = "",
    [string]$SprintReportPath = "",
    [string]$ObservationPath = "",
    [string]$StatePath = "",
    [string]$LedgerPath = "",
    [double]$DailyLossLimitQuote = 50.0,
    [string]$RunId = "",
    [string]$ActiveRunGatePath = "",
    [string]$Reason = "Explicitly rejected as incomplete; preserve for diagnostics only.",
    [switch]$ConfirmedPaperForward,
    [ValidateSet("data_quality", "execution_quality", "reconciliation", "manual_stop")]
    [string]$PaperIncidentType = "manual_stop",
    [switch]$Resume,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Config) {
    $Config = Join-Path $PSScriptRoot "config.json"
}

$pythonCandidates = @(
    $env:TRADING_MVP_PYTHON,
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    "C:\Program Files\Python313\python.exe",
    "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe"
) | Where-Object { $_ }

$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = $pythonCmd.Source
    }
}
if (-not $python) {
    throw "Не найден Python. Задайте TRADING_MVP_PYTHON или создайте .venv."
}

$cli = Join-Path $PSScriptRoot "src\cli.py"
$fastEdgeCli = Join-Path $PSScriptRoot "src\fast_edge.py"
$residualDispersionCli = Join-Path $PSScriptRoot "src\residual_dispersion.py"
$lotteryMaxCli = Join-Path $PSScriptRoot "src\lottery_max_evaluator.py"
$fundingPressureCli = Join-Path $PSScriptRoot "src\funding_pressure_reversal.py"
$wickRejectionCli = Join-Path $PSScriptRoot "src\wick_rejection_reversal.py"
$weekendLiquidityCli = Join-Path $PSScriptRoot "src\weekend_liquidity_window.py"
$feasibilityGateCli = Join-Path $PSScriptRoot "src\feasibility_gate.py"
$dataTrackContractCli = Join-Path $PSScriptRoot "src\data_track_contract.py"
$nightSchedulePlanCli = Join-Path $PSScriptRoot "src\night_schedule_plan.py"
$nightScheduleStatusCli = Join-Path $PSScriptRoot "src\night_schedule_status.py"
$nightScheduleQualityCli = Join-Path $PSScriptRoot "src\night_schedule_quality.py"
$pitMembershipDriftFutilityCli = Join-Path $PSScriptRoot "src\pit_membership_drift_futility.py"
$pitMembershipDriftCli = Join-Path $PSScriptRoot "src\pit_membership_drift_evaluator.py"
$pitMembershipDriftProbeCli = Join-Path $PSScriptRoot "src\pit_membership_drift_execution_probe.py"
$pitMembershipDriftPaperCli = Join-Path $PSScriptRoot "src\pit_membership_drift_paper_forward.py"
$historicalBasisEdgeCli = Join-Path $PSScriptRoot "src\historical_basis_edge.py"
$historicalBasisUniverseCli = Join-Path $PSScriptRoot "src\historical_basis_universe.py"
$historicalBasisCollectorCli = Join-Path $PSScriptRoot "src\historical_basis_collector.py"
$historicalBasisQualityCli = Join-Path $PSScriptRoot "src\historical_basis_quality.py"
$historicalBasisEvaluatorCli = Join-Path $PSScriptRoot "src\historical_basis_evaluator.py"
$historicalBasisProbeCli = Join-Path $PSScriptRoot "src\historical_basis_probe.py"
$basisPaperOmsCli = Join-Path $PSScriptRoot "src\basis_paper_oms.py"
$historicalBasisCodeSnapshotCli = Join-Path $PSScriptRoot "src\historical_basis_code_snapshot.py"
$historicalBasisV2PreflightCli = Join-Path $PSScriptRoot "src\historical_basis_v2_preflight.py"
$historicalBasisV2Cli = Join-Path $PSScriptRoot "src\historical_basis_v2.py"
$historicalBasisV2CollectorCli = Join-Path $PSScriptRoot "src\historical_basis_v2_collector.py"
$historicalBasisV2QualityCli = Join-Path $PSScriptRoot "src\historical_basis_v2_quality.py"
$historicalBasisV2PostprocessCli = Join-Path $PSScriptRoot "src\historical_basis_v2_postprocess.py"
$historicalBasisV2OosPostprocessCli = Join-Path $PSScriptRoot "src\historical_basis_v2_oos_postprocess.py"
$historicalBasisV2EvaluatorCli = Join-Path $PSScriptRoot "src\historical_basis_v2_evaluator.py"
$historicalBasisV2ReportCli = Join-Path $PSScriptRoot "src\historical_basis_v2_report.py"
$historicalBasisV2ExecutionProbeCli = Join-Path $PSScriptRoot "src\historical_basis_v2_execution_probe.py"
$historicalBasisV2PaperOmsCli = Join-Path $PSScriptRoot "src\historical_basis_v2_paper_oms.py"
$paperObserverRuntimeCli = Join-Path $PSScriptRoot "src\paper_observer_runtime.py"
$historicalBasisV2CacheAuditCli = Join-Path $ProjectRoot "tools\audit_historical_basis_v2_cache.py"
$fundingRegimePersistenceV2Cli = Join-Path $PSScriptRoot "src\funding_regime_persistence_v2.py"
$fundingRegimePersistenceV2EvaluatorCli = Join-Path $PSScriptRoot "src\funding_regime_persistence_v2_evaluator.py"
$fundingRegimePersistenceV2OosCli = Join-Path $PSScriptRoot "src\funding_regime_persistence_v2_oos.py"

# --- Modular Tool Helper Imports ---
. (Join-Path $ProjectRoot "tools\trading_gate_assertions.ps1")
. (Join-Path $ProjectRoot "tools\trading_process_helpers.ps1")
. (Join-Path $ProjectRoot "tools\trading_log_formatters.ps1")

function Set-RunTimedOutIncomplete {
    param([string]$TimedOutAction)
    Set-RunTimedOutIncompleteHelper -TimedOutAction $TimedOutAction -MaxRuntimeSecVal $MaxRuntimeSec -CustomGatePath $ActiveRunGatePath
}

function Invoke-TradingMvpCli {
    param(
        [object[]]$ArgsList,
        [string]$ScriptPath = $cli
    )

    if ($MaxRuntimeSec -lt 1 -or $MaxRuntimeSec -gt 10800) {
        throw "MaxRuntimeSec must be in [1, 10800]."
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $python
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $false
    $startInfo.RedirectStandardError = $false
    $startInfo.WorkingDirectory = $ProjectRoot
    $startInfo.ArgumentList.Add($ScriptPath)
    foreach ($argument in $ArgsList) {
        $startInfo.ArgumentList.Add([string]$argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Failed to start Python process: $ScriptPath"
    }
    if (-not $process.WaitForExit($MaxRuntimeSec * 1000)) {
        try { $process.Kill($true) } catch { }
        try { $process.WaitForExit(5000) } catch { }
        Set-RunTimedOutIncomplete -TimedOutAction $Action
        throw "Process exceeded MaxRuntimeSec=$MaxRuntimeSec and was terminated: $ScriptPath"
    }
    if ($process.ExitCode -ne 0) {
        exit $process.ExitCode
    }
}


Push-Location $ProjectRoot
try {
    switch ($Action) {
        "collect" {
            Invoke-TradingMvpCli -ArgsList @("--config", $Config, "collect", "--seconds", $Seconds)
            break
        }
        "backtest" {
            Invoke-TradingMvpCli -ArgsList @("--config", $Config, "backtest")
            break
        }
        "run" {
            Invoke-TradingMvpCli -ArgsList @("--config", $Config, "run", "--mode", $Mode, "--cycles", $Cycles)
            break
        }
        "universe" {
            Invoke-TradingMvpCli -ArgsList @("--config", $Config, "universe")
            break
        }
        "multi-run" {
            $argsList = @("--config", $Config, "multi-run", "--exchanges", $Exchanges, "--max-pairs-per-exchange", $MaxPairsPerExchange, "--max-symbols", $MaxSymbols, "--paper-notional-quote", $PaperNotionalQuote)
            if ($DurationSec -gt 0) {
                $argsList += @("--duration-sec", $DurationSec)
            } else {
                $argsList += @("--cycles", $Cycles)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "ws-collect" {
            $duration = $DurationSec
            if ($duration -le 0) {
                $duration = $Seconds
            }
            $argsList = @("--config", $Config, "ws-collect", "--exchanges", $Exchanges, "--max-pairs-per-exchange", $MaxPairsPerExchange, "--max-symbols", $MaxSymbols, "--duration-sec", $duration, "--update-interval", $UpdateInterval)
            if ($InputPath) {
                $argsList += @("--universe", $InputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "ws-normalize" {
            $argsList = @("--config", $Config, "ws-normalize")
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "ws-data-quality" {
            $argsList = @(
                "--config", $Config,
                "ws-data-quality",
                "--min-rows", $WsQualityMinRows,
                "--min-exchanges", $WsQualityMinExchanges,
                "--min-markets", $WsQualityMinMarkets,
                "--min-span-hours", $WsQualityMinSpanHours,
                "--min-duration-ratio", $WsQualityMinDurationRatio,
                "--max-parse-error-rate", $WsQualityMaxParseErrorRate,
                "--required-event-kinds", $WsQualityRequiredEventKinds,
                "--min-markets-with-required-kinds", $WsQualityMinMarketsWithRequiredKinds,
                "--max-market-event-share", $WsQualityMaxMarketEventShare,
                "--max-gap-sec", $WsQualityMaxGapSec,
                "--max-manifest-error-count", $WsQualityMaxManifestErrorCount
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "ws-postprocess" {
            $argsList = @(
                "--config", $Config,
                "ws-postprocess",
                "--min-rows", $WsQualityMinRows,
                "--min-exchanges", $WsQualityMinExchanges,
                "--min-markets", $WsQualityMinMarkets,
                "--min-span-hours", $WsQualityMinSpanHours,
                "--min-duration-ratio", $WsQualityMinDurationRatio,
                "--max-parse-error-rate", $WsQualityMaxParseErrorRate,
                "--required-event-kinds", $WsQualityRequiredEventKinds,
                "--min-markets-with-required-kinds", $WsQualityMinMarketsWithRequiredKinds,
                "--max-market-event-share", $WsQualityMaxMarketEventShare,
                "--max-gap-sec", $WsQualityMaxGapSec,
                "--max-manifest-error-count", $WsQualityMaxManifestErrorCount
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($OutputPath) {
                $argsList += @("--normalized-output", $OutputPath)
            }
            if ($ReportOutputPath) {
                $argsList += @("--quality-output", $ReportOutputPath)
            }
            if ($PostprocessReportPath) {
                $argsList += @("--output", $PostprocessReportPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "perp-collect" {
            $argsList = @(
                "--config", $Config,
                "perp-collect",
                "--exchanges", $Exchanges,
                "--max-pairs-per-exchange", $MaxPairsPerExchange,
                "--max-symbols", $MaxSymbols,
                "--poll-interval-sec", $PollIntervalSec,
                "--depth-limit", $DepthLimit,
                "--trades-limit", $TradesLimit
            )
            if ($DurationSec -gt 0) {
                $argsList += @("--duration-sec", $DurationSec)
            } else {
                $argsList += @("--cycles", $Cycles)
            }
            if ($InputPath) {
                $argsList += @("--universe", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "perp-report" {
            $argsList = @("--config", $Config, "perp-report")
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "event-quality-report" {
            $argsList = @(
                "--config", $Config,
                "event-quality-report",
                "--lookback-sec", $EventLookbackSec,
                "--horizon-sec", $EventHorizonSec,
                "--min-sweep-notional-quote", $EventMinSweepNotionalQuote,
                "--reclaim-bps", $EventReclaimBps,
                "--target-bps", $EventTargetBps,
                "--stop-bps", $EventStopBps,
                "--max-pre-spread-bps", $EventMaxPreSpreadBps,
                "--event-cooldown-sec", $EventCooldownSec,
                "--max-events", $EventMaxEvents
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "event-slice-optimizer" {
            $argsList = @(
                "--config", $Config,
                "event-slice-optimizer",
                "--min-events", $SliceMinEvents,
                "--min-reclaimed", $SliceMinReclaimed,
                "--min-target-before-stop-rate", $SliceMinTargetBeforeStopRate,
                "--min-target-rate-all", $SliceMinTargetRateAll,
                "--max-false-sweep-rate", $SliceMaxFalseSweepRate,
                "--max-avg-adverse-bps", $SliceMaxAvgAdverseBps,
                "--min-favorable-to-adverse", $SliceMinFavorableToAdverse,
                "--min-sweep-intensity-bps", $SliceMinSweepIntensityBps,
                "--max-time-to-reclaim-sec", $SliceMaxTimeToReclaimSec,
                "--max-pre-spread-bps", $SliceMaxPreSpreadBps,
                "--max-abs-basis-bps", $SliceMaxAbsBasisBps,
                "--min-trade-notional-quote", $SliceMinTradeNotionalQuote,
                "--top-n", $TopN
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "event-validation-report" {
            $argsList = @(
                "--config", $Config,
                "event-validation-report",
                "--train-fraction", $ValidationTrainFraction,
                "--walk-forward-windows", $ValidationWalkForwardWindows,
                "--walk-forward-min-pass-ratio", $ValidationWalkForwardMinPassRatio,
                "--min-events", $SliceMinEvents,
                "--min-reclaimed", $SliceMinReclaimed,
                "--min-target-before-stop-rate", $SliceMinTargetBeforeStopRate,
                "--min-target-rate-all", $SliceMinTargetRateAll,
                "--max-false-sweep-rate", $ValidationMaxFalseSweepRate,
                "--max-avg-adverse-bps", $SliceMaxAvgAdverseBps,
                "--min-favorable-to-adverse", $ValidationMinFavorableToAdverse,
                "--min-sweep-intensity-bps", $SliceMinSweepIntensityBps,
                "--max-time-to-reclaim-sec", $SliceMaxTimeToReclaimSec,
                "--max-pre-spread-bps", $SliceMaxPreSpreadBps,
                "--max-abs-basis-bps", $SliceMaxAbsBasisBps,
                "--min-trade-notional-quote", $SliceMinTradeNotionalQuote,
                "--stress-favorable-haircut-bps", $ValidationStressFavorableHaircutBps,
                "--stress-adverse-widen-bps", $ValidationStressAdverseWidenBps,
                "--stress-target-bps", $ValidationStressTargetBps,
                "--stress-stop-bps", $ValidationStressStopBps,
                "--top-n", $TopN
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "cross-venue-dislocation" {
            if (-not $InputPath) {
                throw "cross-venue-dislocation requires -InputPath pointing to a clean normalized WS JSONL file."
            }
            $argsList = @(
                "--config", $Config,
                "cross-venue-dislocation",
                "--input", $InputPath,
                "--quote", $Quote,
                "--stale-quote-sec", $CrossVenueStaleQuoteSec,
                "--min-top-notional-quote", $CrossVenueMinTopNotionalQuote,
                "--round-trip-fee-bps", $CrossVenueRoundTripFeeBps,
                "--slippage-bps", $CrossVenueSlippageBps,
                "--inventory-rebalance-buffer-bps", $CrossVenueInventoryRebalanceBufferBps,
                "--min-net-edge-bps", $CrossVenueMinNetEdgeBps,
                "--cooldown-sec", $CrossVenueCooldownSec,
                "--max-rows", $CrossVenueMaxRows,
                "--max-events", $CrossVenueMaxEvents,
                "--progress-every-rows", $CrossVenueProgressEveryRows
            )
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($CrossVenueIncludeBases) {
                $argsList += @("--include-bases", $CrossVenueIncludeBases)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "perp-postprocess" {
            $argsList = @("--config", $Config, "perp-postprocess")
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($ReportOutputPath) {
                $argsList += @("--report-output", $ReportOutputPath)
            }
            if ($GridOutputPath) {
                $argsList += @("--grid-output", $GridOutputPath)
            }
            if ($AllowPartial) {
                $argsList += @("--allow-partial")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "ws-replay" {
            $argsList = @(
                "--config", $Config,
                "ws-replay",
                "--signal-type", $SignalType,
                "--notional-quote", $NotionalQuote,
                "--execution-mode", $ExecutionMode,
                "--taker-fee-bps", $TakerFeeBps,
                "--maker-fee-bps", $MakerFeeBps,
                "--slippage-bps", $SlippageBps,
                "--max-quote-age-sec", $MaxQuoteAgeSec,
                "--latency-ms", $LatencyMs,
                "--flow-window-sec", $FlowWindowSec,
                "--max-open-positions", $MaxOpenPositions,
                "--maker-queue-ahead-qty", $MakerQueueAheadQty,
                "--maker-queue-model", $MakerQueueModel,
                "--maker-queue-ahead-fraction", $MakerQueueAheadFraction,
                "--maker-order-ttl-sec", $MakerOrderTtlSec,
                "--quality-window-sec", $QualityWindowSec,
                "--quality-min-trade-count", $QualityMinTradeCount,
                "--quality-min-trade-notional", $QualityMinTradeNotional,
                "--quality-max-avg-spread-bps", $QualityMaxAvgSpreadBps,
                "--quality-min-quote-updates", $QualityMinQuoteUpdates,
                "--quality-min-top-qty", $QualityMinTopQty,
                "--min-net-take-profit-bps", $MinNetTakeProfitBps,
                "--sweep-v2-allowed-markets", $SweepV2AllowedMarkets,
                "--sweep-v2-side", $SweepV2Side,
                "--sweep-v2-min-trade-notional-quote", $SweepV2MinTradeNotionalQuote,
                "--sweep-v2-min-intensity-bps", $SweepV2MinIntensityBps,
                "--sweep-v2-max-pre-spread-bps", $SweepV2MaxPreSpreadBps,
                "--sweep-v2-max-reclaim-sec", $SweepV2MaxReclaimSec,
                "--sweep-v2-event-cooldown-sec", $SweepV2EventCooldownSec
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($VenueCostsJson) {
                $argsList += @("--venue-costs-json", $VenueCostsJson)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($AllowShort) {
                $argsList += @("--allow-short")
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "ws-grid-search" {
            $argsList = @(
                "--config", $Config,
                "ws-grid-search",
                "--notional-quote", $NotionalQuote,
                "--execution-mode", $ExecutionMode,
                "--taker-fee-bps", $TakerFeeBps,
                "--maker-fee-bps", $MakerFeeBps,
                "--slippage-bps", $SlippageBps,
                "--max-quote-age-sec", $MaxQuoteAgeSec,
                "--latency-ms", $LatencyMs,
                "--flow-window-sec", $FlowWindowSec,
                "--max-open-positions", $MaxOpenPositions,
                "--maker-queue-ahead-qty", $MakerQueueAheadQty,
                "--maker-queue-model", $MakerQueueModel,
                "--maker-queue-ahead-fraction", $MakerQueueAheadFraction,
                "--maker-order-ttl-sec", $MakerOrderTtlSec,
                "--quality-window-sec", $QualityWindowSec,
                "--quality-min-trade-count", $QualityMinTradeCount,
                "--quality-min-trade-notional", $QualityMinTradeNotional,
                "--quality-max-avg-spread-bps", $QualityMaxAvgSpreadBps,
                "--quality-min-quote-updates", $QualityMinQuoteUpdates,
                "--quality-min-top-qty", $QualityMinTopQty,
                "--min-net-take-profit-bps", $MinNetTakeProfitBps,
                "--sweep-v2-allowed-markets", $SweepV2AllowedMarkets,
                "--sweep-v2-side", $SweepV2Side,
                "--sweep-v2-min-trade-notional-quote", $SweepV2MinTradeNotionalQuote,
                "--sweep-v2-min-intensity-bps", $SweepV2MinIntensityBps,
                "--sweep-v2-max-pre-spread-bps", $SweepV2MaxPreSpreadBps,
                "--sweep-v2-max-reclaim-sec", $SweepV2MaxReclaimSec,
                "--sweep-v2-event-cooldown-sec", $SweepV2EventCooldownSec,
                "--grid-signal-type", $GridSignalType,
                "--entry-imbalance-abs", $GridImbalance,
                "--entry-signed-flow-notional", $GridFlow,
                "--max-spread-bps", $GridSpread,
                "--take-profit-bps", $GridTakeProfit,
                "--stop-loss-bps", $GridStopLoss,
                "--max-hold-sec", $GridMaxHoldSec,
                "--min-trades", $MinTrades,
                "--min-win-rate", $MinWinRate,
                "--min-expectancy-quote", $MinExpectancyQuote,
                "--min-net-pnl-quote", $MinNetPnlQuote,
                "--min-profit-factor", $MinProfitFactor,
                "--max-drawdown-quote", $MaxDrawdownQuote,
                "--top-n", $TopN,
                "--max-grid-combinations", $MaxGridCombinations
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($VenueCostsJson) {
                $argsList += @("--venue-costs-json", $VenueCostsJson)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($AllowShort) {
                $argsList += @("--allow-short")
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "perp-replay" {
            $argsList = @(
                "--config", $Config,
                "perp-replay",
                "--signal-type", $SignalType,
                "--notional-quote", $NotionalQuote,
                "--execution-mode", $ExecutionMode,
                "--taker-fee-bps", $TakerFeeBps,
                "--maker-fee-bps", $MakerFeeBps,
                "--slippage-bps", $SlippageBps,
                "--max-quote-age-sec", $MaxQuoteAgeSec,
                "--latency-ms", $LatencyMs,
                "--flow-window-sec", $FlowWindowSec,
                "--max-open-positions", $MaxOpenPositions,
                "--maker-queue-ahead-qty", $MakerQueueAheadQty,
                "--maker-queue-model", $MakerQueueModel,
                "--maker-queue-ahead-fraction", $MakerQueueAheadFraction,
                "--maker-order-ttl-sec", $MakerOrderTtlSec,
                "--quality-window-sec", $QualityWindowSec,
                "--quality-min-trade-count", $QualityMinTradeCount,
                "--quality-min-trade-notional", $QualityMinTradeNotional,
                "--quality-max-avg-spread-bps", $QualityMaxAvgSpreadBps,
                "--quality-min-quote-updates", $QualityMinQuoteUpdates,
                "--quality-min-top-qty", $QualityMinTopQty,
                "--min-net-take-profit-bps", $MinNetTakeProfitBps,
                "--sweep-v2-allowed-markets", $SweepV2AllowedMarkets,
                "--sweep-v2-side", $SweepV2Side,
                "--sweep-v2-min-trade-notional-quote", $SweepV2MinTradeNotionalQuote,
                "--sweep-v2-min-intensity-bps", $SweepV2MinIntensityBps,
                "--sweep-v2-max-pre-spread-bps", $SweepV2MaxPreSpreadBps,
                "--sweep-v2-max-reclaim-sec", $SweepV2MaxReclaimSec,
                "--sweep-v2-event-cooldown-sec", $SweepV2EventCooldownSec
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($VenueCostsJson) {
                $argsList += @("--venue-costs-json", $VenueCostsJson)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "perp-grid-search" {
            $argsList = @(
                "--config", $Config,
                "perp-grid-search",
                "--notional-quote", $NotionalQuote,
                "--execution-mode", $ExecutionMode,
                "--taker-fee-bps", $TakerFeeBps,
                "--maker-fee-bps", $MakerFeeBps,
                "--slippage-bps", $SlippageBps,
                "--max-quote-age-sec", $MaxQuoteAgeSec,
                "--latency-ms", $LatencyMs,
                "--flow-window-sec", $FlowWindowSec,
                "--max-open-positions", $MaxOpenPositions,
                "--maker-queue-ahead-qty", $MakerQueueAheadQty,
                "--maker-queue-model", $MakerQueueModel,
                "--maker-queue-ahead-fraction", $MakerQueueAheadFraction,
                "--maker-order-ttl-sec", $MakerOrderTtlSec,
                "--quality-window-sec", $QualityWindowSec,
                "--quality-min-trade-count", $QualityMinTradeCount,
                "--quality-min-trade-notional", $QualityMinTradeNotional,
                "--quality-max-avg-spread-bps", $QualityMaxAvgSpreadBps,
                "--quality-min-quote-updates", $QualityMinQuoteUpdates,
                "--quality-min-top-qty", $QualityMinTopQty,
                "--min-net-take-profit-bps", $MinNetTakeProfitBps,
                "--sweep-v2-allowed-markets", $SweepV2AllowedMarkets,
                "--sweep-v2-side", $SweepV2Side,
                "--sweep-v2-min-trade-notional-quote", $SweepV2MinTradeNotionalQuote,
                "--sweep-v2-min-intensity-bps", $SweepV2MinIntensityBps,
                "--sweep-v2-max-pre-spread-bps", $SweepV2MaxPreSpreadBps,
                "--sweep-v2-max-reclaim-sec", $SweepV2MaxReclaimSec,
                "--sweep-v2-event-cooldown-sec", $SweepV2EventCooldownSec,
                "--grid-signal-type", $GridSignalType,
                "--entry-imbalance-abs", $GridImbalance,
                "--entry-signed-flow-notional", $GridFlow,
                "--max-spread-bps", $GridSpread,
                "--take-profit-bps", $GridTakeProfit,
                "--stop-loss-bps", $GridStopLoss,
                "--max-hold-sec", $GridMaxHoldSec,
                "--min-trades", $MinTrades,
                "--min-win-rate", $MinWinRate,
                "--min-expectancy-quote", $MinExpectancyQuote,
                "--min-net-pnl-quote", $MinNetPnlQuote,
                "--min-profit-factor", $MinProfitFactor,
                "--max-drawdown-quote", $MaxDrawdownQuote,
                "--top-n", $TopN,
                "--max-grid-combinations", $MaxGridCombinations
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($VenueCostsJson) {
                $argsList += @("--venue-costs-json", $VenueCostsJson)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-scan" {
            $argsList = @(
                "--config", $Config,
                "funding-scan",
                "--exchanges", $Exchanges,
                "--quote", "USDT",
                "--max-symbols", $MaxSymbols,
                "--max-pairs-per-exchange", $MaxPairsPerExchange,
                "--notional-quote", $NotionalQuote,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-volume-24h-quote", $FundingMinVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--target-hold-intervals", $FundingTargetHoldIntervals,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--max-break-even-hours", $FundingMaxBreakEvenHours
            )
            if ($InputPath) {
                $argsList += @("--universe", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-collect" {
            $argsList = @(
                "--config", $Config,
                "funding-collect",
                "--exchanges", $Exchanges,
                "--quote", "USDT",
                "--max-symbols", $MaxSymbols,
                "--max-pairs-per-exchange", $MaxPairsPerExchange,
                "--cycles", $Cycles,
                "--poll-interval-sec", $PollIntervalSec,
                "--notional-quote", $NotionalQuote,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-volume-24h-quote", $FundingMinVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--target-hold-intervals", $FundingTargetHoldIntervals,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--max-break-even-hours", $FundingMaxBreakEvenHours
            )
            if ($InputPath) {
                $argsList += @("--universe", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($FundingResume) {
                $argsList += @("--resume")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-status" {
            $argsList = @(
                "--config", $Config,
                "funding-status",
                "--stale-after-sec", $FundingStatusStaleAfterSec,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-required-row-fields", $FundingQualityRequiredRowFields,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-collect-diagnostics" {
            $argsList = @(
                "--config", $Config,
                "funding-collect-diagnostics",
                "--top-n", $TopN
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($FundingQualityRequiredRowFields) {
                $argsList += @("--required-row-fields", $FundingQualityRequiredRowFields)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-wait-ready" {
            $argsList = @(
                "--config", $Config,
                "funding-wait-ready",
                "--timeout-sec", $Seconds,
                "--poll-interval-sec", $PollIntervalSec,
                "--stale-after-sec", $FundingStatusStaleAfterSec,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-required-row-fields", $FundingQualityRequiredRowFields,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-coverage" {
            $argsList = @(
                "--config", $Config,
                "funding-coverage",
                "--exchanges", $Exchanges,
                "--quote", $Quote,
                "--max-symbols", $MaxSymbols
            )
            if ($InputPath) {
                $argsList += @("--universe", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($MatchedUniverseOutputPath) {
                $argsList += @("--matched-universe-output", $MatchedUniverseOutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-rank" {
            $argsList = @(
                "--config", $Config,
                "funding-rank",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-funding-rate", $FundingMinRate,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-gate-report" {
            $argsList = @(
                "--config", $Config,
                "funding-gate-report",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-funding-rate", $FundingMinRate,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($QualityUniverseOutputPath) {
                $argsList += @("--quality-universe-output", $QualityUniverseOutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-regime-report" {
            $argsList = @(
                "--config", $Config,
                "funding-regime-report",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-funding-rate", $FundingMinRate,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-frontier-report" {
            $argsList = @(
                "--config", $Config,
                "funding-frontier-report",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-funding-rate", $FundingMinRate,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-decision-report" {
            $argsList = @(
                "--config", $Config,
                "funding-decision-report",
                "--stale-after-sec", $FundingStatusStaleAfterSec,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($FundingQualityRequiredRowFields) {
                $argsList += @("--quality-required-row-fields", $FundingQualityRequiredRowFields)
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($PostprocessReportPath) {
                $argsList += @("--postprocess-report", $PostprocessReportPath)
            }
            if ($GateReportPath) {
                $argsList += @("--gate-report", $GateReportPath)
            }
            if ($RegimeReportPath) {
                $argsList += @("--regime-report", $RegimeReportPath)
            }
            if ($FrontierReportPath) {
                $argsList += @("--frontier-report", $FrontierReportPath)
            }
            if ($SensitivityReportPath) {
                $argsList += @("--sensitivity-report", $SensitivityReportPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-progress-report" {
            $argsList = @(
                "--config", $Config,
                "funding-progress-report",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-funding-rate", $FundingMinRate,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-backtest" {
            $argsList = @(
                "--config", $Config,
                "funding-backtest",
                "--notional-quote", $NotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps
            )
            if ($VenueCostsJson) {
                $argsList += @("--venue-costs-json", $VenueCostsJson)
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-sensitivity" {
            $argsList = @(
                "--config", $Config,
                "funding-sensitivity",
                "--spot-fee-bps-list", $FundingSensitivitySpotFeeBps,
                "--perp-fee-bps-list", $FundingSensitivityPerpFeeBps,
                "--slippage-bps-list", $FundingSensitivitySlippageBps,
                "--target-hold-intervals-list", $FundingSensitivityTargetHoldIntervals,
                "--max-break-even-hours-list", $FundingSensitivityMaxBreakEvenHours,
                "--top-n", $TopN,
                "--notional-quote", $NotionalQuote,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps,
                "--accept-min-trades", $FundingAcceptMinTrades,
                "--accept-min-win-rate", $FundingAcceptMinWinRate,
                "--accept-min-expectancy-quote", $FundingAcceptMinExpectancyQuote,
                "--accept-min-net-pnl-quote", $FundingAcceptMinNetPnlQuote,
                "--accept-max-drawdown-quote", $FundingAcceptMaxDrawdownQuote,
                "--accept-min-profit-factor", $FundingAcceptMinProfitFactor,
                "--accept-min-markets", $FundingAcceptMinMarkets,
                "--accept-max-market-trade-share", $FundingAcceptMaxMarketTradeShare,
                "--accept-min-exchanges", $FundingAcceptMinExchanges,
                "--accept-max-exchange-trade-share", $FundingAcceptMaxExchangeTradeShare,
                "--accept-min-profitable-windows", $FundingAcceptMinProfitableWindows,
                "--accept-max-window-pnl-share", $FundingAcceptMaxWindowPnlShare,
                "--stress-adverse-basis-bps", $FundingStressAdverseBasisBps,
                "--stress-spread-widen-bps", $FundingStressSpreadWidenBps,
                "--stress-funding-flip-bps", $FundingStressFundingFlipBps,
                "--stress-min-net-pnl-quote", $FundingStressMinNetPnlQuote,
                "--stress-max-drawdown-quote", $FundingStressMaxDrawdownQuote,
                "--oos-train-fraction", $FundingOosTrainFraction,
                "--oos-min-train-rows", $FundingOosMinTrainRows,
                "--oos-min-rows", $FundingOosMinRows,
                "--oos-min-train-span-hours", $FundingOosMinTrainSpanHours,
                "--oos-min-span-hours", $FundingOosMinSpanHours,
                "--walk-train-rows", $FundingWalkTrainRows,
                "--walk-test-rows", $FundingWalkTestRows,
                "--walk-step-rows", $FundingWalkStepRows,
                "--walk-min-windows", $FundingWalkMinWindows,
                "--walk-min-accepted-windows", $FundingWalkMinAcceptedWindows,
                "--walk-min-accepted-ratio", $FundingWalkMinAcceptedRatio,
                "--walk-min-train-span-hours", $FundingWalkMinTrainSpanHours,
                "--walk-min-test-span-hours", $FundingWalkMinTestSpanHours
            )
            if ($FundingStress) {
                $argsList += @("--stress-enabled")
            }
            if ($FundingSensitivityOos) {
                $argsList += @("--sensitivity-oos")
            }
            if ($FundingSensitivityWalkForward) {
                $argsList += @("--sensitivity-walk-forward")
            }
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-oos-backtest" {
            $argsList = @(
                "--config", $Config,
                "funding-oos-backtest",
                "--notional-quote", $NotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps,
                "--train-fraction", $FundingOosTrainFraction,
                "--min-train-rows", $FundingOosMinTrainRows,
                "--min-oos-rows", $FundingOosMinRows,
                "--min-train-span-hours", $FundingOosMinTrainSpanHours,
                "--min-oos-span-hours", $FundingOosMinSpanHours,
                "--accept-min-trades", $FundingAcceptMinTrades,
                "--accept-min-win-rate", $FundingAcceptMinWinRate,
                "--accept-min-expectancy-quote", $FundingAcceptMinExpectancyQuote,
                "--accept-min-net-pnl-quote", $FundingAcceptMinNetPnlQuote,
                "--accept-max-drawdown-quote", $FundingAcceptMaxDrawdownQuote,
                "--accept-min-profit-factor", $FundingAcceptMinProfitFactor,
                "--accept-min-markets", $FundingAcceptMinMarkets,
                "--accept-max-market-trade-share", $FundingAcceptMaxMarketTradeShare,
                "--accept-min-exchanges", $FundingAcceptMinExchanges,
                "--accept-max-exchange-trade-share", $FundingAcceptMaxExchangeTradeShare,
                "--accept-min-profitable-windows", $FundingAcceptMinProfitableWindows,
                "--accept-max-window-pnl-share", $FundingAcceptMaxWindowPnlShare,
                "--stress-adverse-basis-bps", $FundingStressAdverseBasisBps,
                "--stress-spread-widen-bps", $FundingStressSpreadWidenBps,
                "--stress-funding-flip-bps", $FundingStressFundingFlipBps,
                "--stress-min-net-pnl-quote", $FundingStressMinNetPnlQuote,
                "--stress-max-drawdown-quote", $FundingStressMaxDrawdownQuote
            )
            if ($FundingStress) {
                $argsList += @("--stress-enabled")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-walk-forward" {
            $argsList = @(
                "--config", $Config,
                "funding-walk-forward",
                "--notional-quote", $NotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps,
                "--walk-train-rows", $FundingWalkTrainRows,
                "--walk-test-rows", $FundingWalkTestRows,
                "--walk-step-rows", $FundingWalkStepRows,
                "--walk-min-windows", $FundingWalkMinWindows,
                "--walk-min-accepted-windows", $FundingWalkMinAcceptedWindows,
                "--walk-min-accepted-ratio", $FundingWalkMinAcceptedRatio,
                "--walk-min-train-span-hours", $FundingWalkMinTrainSpanHours,
                "--walk-min-test-span-hours", $FundingWalkMinTestSpanHours,
                "--accept-min-trades", $FundingAcceptMinTrades,
                "--accept-min-win-rate", $FundingAcceptMinWinRate,
                "--accept-min-expectancy-quote", $FundingAcceptMinExpectancyQuote,
                "--accept-min-net-pnl-quote", $FundingAcceptMinNetPnlQuote,
                "--accept-max-drawdown-quote", $FundingAcceptMaxDrawdownQuote,
                "--accept-min-profit-factor", $FundingAcceptMinProfitFactor,
                "--accept-min-markets", $FundingAcceptMinMarkets,
                "--accept-max-market-trade-share", $FundingAcceptMaxMarketTradeShare,
                "--accept-min-exchanges", $FundingAcceptMinExchanges,
                "--accept-max-exchange-trade-share", $FundingAcceptMaxExchangeTradeShare,
                "--accept-min-profitable-windows", $FundingAcceptMinProfitableWindows,
                "--accept-max-window-pnl-share", $FundingAcceptMaxWindowPnlShare,
                "--stress-adverse-basis-bps", $FundingStressAdverseBasisBps,
                "--stress-spread-widen-bps", $FundingStressSpreadWidenBps,
                "--stress-funding-flip-bps", $FundingStressFundingFlipBps,
                "--stress-min-net-pnl-quote", $FundingStressMinNetPnlQuote,
                "--stress-max-drawdown-quote", $FundingStressMaxDrawdownQuote
            )
            if ($FundingStress) {
                $argsList += @("--stress-enabled")
            }
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-postprocess" {
            $argsList = @(
                "--config", $Config,
                "funding-postprocess",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps,
                "--notional-quote", $NotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--accept-min-trades", $FundingAcceptMinTrades,
                "--accept-min-win-rate", $FundingAcceptMinWinRate,
                "--accept-min-expectancy-quote", $FundingAcceptMinExpectancyQuote,
                "--accept-min-net-pnl-quote", $FundingAcceptMinNetPnlQuote,
                "--accept-max-drawdown-quote", $FundingAcceptMaxDrawdownQuote,
                "--accept-min-profit-factor", $FundingAcceptMinProfitFactor,
                "--accept-min-markets", $FundingAcceptMinMarkets,
                "--accept-max-market-trade-share", $FundingAcceptMaxMarketTradeShare,
                "--accept-min-exchanges", $FundingAcceptMinExchanges,
                "--accept-max-exchange-trade-share", $FundingAcceptMaxExchangeTradeShare,
                "--accept-min-profitable-windows", $FundingAcceptMinProfitableWindows,
                "--accept-max-window-pnl-share", $FundingAcceptMaxWindowPnlShare,
                "--stress-adverse-basis-bps", $FundingStressAdverseBasisBps,
                "--stress-spread-widen-bps", $FundingStressSpreadWidenBps,
                "--stress-funding-flip-bps", $FundingStressFundingFlipBps,
                "--stress-min-net-pnl-quote", $FundingStressMinNetPnlQuote,
                "--stress-max-drawdown-quote", $FundingStressMaxDrawdownQuote,
                "--oos-train-fraction", $FundingOosTrainFraction,
                "--oos-min-train-rows", $FundingOosMinTrainRows,
                "--oos-min-rows", $FundingOosMinRows,
                "--oos-min-train-span-hours", $FundingOosMinTrainSpanHours,
                "--oos-min-span-hours", $FundingOosMinSpanHours,
                "--walk-train-rows", $FundingWalkTrainRows,
                "--walk-test-rows", $FundingWalkTestRows,
                "--walk-step-rows", $FundingWalkStepRows,
                "--walk-min-windows", $FundingWalkMinWindows,
                "--walk-min-accepted-windows", $FundingWalkMinAcceptedWindows,
                "--walk-min-accepted-ratio", $FundingWalkMinAcceptedRatio,
                "--walk-min-train-span-hours", $FundingWalkMinTrainSpanHours,
                "--walk-min-test-span-hours", $FundingWalkMinTestSpanHours,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-required-row-fields", $FundingQualityRequiredRowFields,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence
            )
            if ($FundingStress) {
                $argsList += @("--stress-enabled")
            }
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($ReportOutputPath) {
                $argsList += @("--rank-output", $ReportOutputPath)
            }
            if ($GridOutputPath) {
                $argsList += @("--backtest-output", $GridOutputPath)
            }
            if ($OosOutputPath) {
                $argsList += @("--oos-output", $OosOutputPath)
            }
            if ($WalkForwardOutputPath) {
                $argsList += @("--walk-forward-output", $WalkForwardOutputPath)
            }
            if ($OutputPath) {
                $argsList += @("--postprocess-output", $OutputPath)
            }
            if ($AllowPartial) {
                $argsList += @("--allow-partial")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-finalize" {
            $argsList = @(
                "--config", $Config,
                "funding-finalize",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps,
                "--notional-quote", $NotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--accept-min-trades", $FundingAcceptMinTrades,
                "--accept-min-win-rate", $FundingAcceptMinWinRate,
                "--accept-min-expectancy-quote", $FundingAcceptMinExpectancyQuote,
                "--accept-min-net-pnl-quote", $FundingAcceptMinNetPnlQuote,
                "--accept-max-drawdown-quote", $FundingAcceptMaxDrawdownQuote,
                "--accept-min-profit-factor", $FundingAcceptMinProfitFactor,
                "--accept-min-markets", $FundingAcceptMinMarkets,
                "--accept-max-market-trade-share", $FundingAcceptMaxMarketTradeShare,
                "--accept-min-exchanges", $FundingAcceptMinExchanges,
                "--accept-max-exchange-trade-share", $FundingAcceptMaxExchangeTradeShare,
                "--accept-min-profitable-windows", $FundingAcceptMinProfitableWindows,
                "--accept-max-window-pnl-share", $FundingAcceptMaxWindowPnlShare,
                "--stress-adverse-basis-bps", $FundingStressAdverseBasisBps,
                "--stress-spread-widen-bps", $FundingStressSpreadWidenBps,
                "--stress-funding-flip-bps", $FundingStressFundingFlipBps,
                "--stress-min-net-pnl-quote", $FundingStressMinNetPnlQuote,
                "--stress-max-drawdown-quote", $FundingStressMaxDrawdownQuote,
                "--oos-train-fraction", $FundingOosTrainFraction,
                "--oos-min-train-rows", $FundingOosMinTrainRows,
                "--oos-min-rows", $FundingOosMinRows,
                "--oos-min-train-span-hours", $FundingOosMinTrainSpanHours,
                "--oos-min-span-hours", $FundingOosMinSpanHours,
                "--walk-train-rows", $FundingWalkTrainRows,
                "--walk-test-rows", $FundingWalkTestRows,
                "--walk-step-rows", $FundingWalkStepRows,
                "--walk-min-windows", $FundingWalkMinWindows,
                "--walk-min-accepted-windows", $FundingWalkMinAcceptedWindows,
                "--walk-min-accepted-ratio", $FundingWalkMinAcceptedRatio,
                "--walk-min-train-span-hours", $FundingWalkMinTrainSpanHours,
                "--walk-min-test-span-hours", $FundingWalkMinTestSpanHours,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-required-row-fields", $FundingQualityRequiredRowFields,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence,
                "--min-forward-hours", $FundingPaperMinForwardHours,
                "--min-forward-rows", $FundingPaperMinForwardRows,
                "--min-forward-markets", $FundingPaperMinForwardMarkets
            )
            if ($FundingStress) {
                $argsList += @("--stress-enabled")
            }
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($ReportOutputPath) {
                $argsList += @("--rank-output", $ReportOutputPath)
            }
            if ($GridOutputPath) {
                $argsList += @("--backtest-output", $GridOutputPath)
            }
            if ($OosOutputPath) {
                $argsList += @("--oos-output", $OosOutputPath)
            }
            if ($WalkForwardOutputPath) {
                $argsList += @("--walk-forward-output", $WalkForwardOutputPath)
            }
            if ($OutputPath) {
                $argsList += @("--postprocess-output", $OutputPath)
            }
            if ($FundingPlanPath) {
                $argsList += @("--paper-plan-output", $FundingPlanPath)
            }
            if ($PaperOutputPath) {
                $argsList += @("--paper-output", $PaperOutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-final-review" {
            $argsList = @(
                "--config", $Config,
                "funding-final-review",
                "--top-n", $TopN,
                "--min-funding-observations", $FundingMinObservations,
                "--min-funding-positive-ratio", $FundingMinPositiveRatio,
                "--min-funding-persistence-score", $FundingMinPersistenceScore,
                "--funding-persistence-weight", $FundingPersistenceWeight,
                "--min-regime-observations", $FundingMinRegimeObservations,
                "--min-perp-volume-24h-quote", $FundingMinPerpVolume24hQuote,
                "--min-spot-top-notional-quote", $FundingMinSpotTopNotionalQuote,
                "--max-basis-std-bps", $FundingMaxBasisStdBps,
                "--max-avg-spot-spread-bps", $FundingMaxAvgSpotSpreadBps,
                "--max-avg-perp-spread-bps", $FundingMaxAvgPerpSpreadBps,
                "--notional-quote", $NotionalQuote,
                "--spot-fee-bps", $FundingSpotFeeBps,
                "--perp-fee-bps", $FundingPerpFeeBps,
                "--slippage-bps", $SlippageBps,
                "--min-funding-rate", $FundingMinRate,
                "--min-total-score", $FundingMinTotalScore,
                "--max-spot-spread-bps", $FundingMaxSpotSpreadBps,
                "--max-perp-spread-bps", $FundingMaxPerpSpreadBps,
                "--max-abs-basis-bps", $FundingMaxAbsBasisBps,
                "--min-basis-bps", $FundingMinBasisBps,
                "--min-expected-net-carry-bps", $FundingMinExpectedNetCarryBps,
                "--min-risk-adjusted-edge-bps", $FundingMinRiskAdjustedEdgeBps,
                "--basis-risk-multiplier", $FundingBasisRiskMultiplier,
                "--spread-risk-multiplier", $FundingSpreadRiskMultiplier,
                "--max-break-even-hours", $FundingMaxBreakEvenHours,
                "--accept-min-trades", $FundingAcceptMinTrades,
                "--accept-min-win-rate", $FundingAcceptMinWinRate,
                "--accept-min-expectancy-quote", $FundingAcceptMinExpectancyQuote,
                "--accept-min-net-pnl-quote", $FundingAcceptMinNetPnlQuote,
                "--accept-max-drawdown-quote", $FundingAcceptMaxDrawdownQuote,
                "--accept-min-profit-factor", $FundingAcceptMinProfitFactor,
                "--accept-min-markets", $FundingAcceptMinMarkets,
                "--accept-max-market-trade-share", $FundingAcceptMaxMarketTradeShare,
                "--accept-min-exchanges", $FundingAcceptMinExchanges,
                "--accept-max-exchange-trade-share", $FundingAcceptMaxExchangeTradeShare,
                "--accept-min-profitable-windows", $FundingAcceptMinProfitableWindows,
                "--accept-max-window-pnl-share", $FundingAcceptMaxWindowPnlShare,
                "--stress-adverse-basis-bps", $FundingStressAdverseBasisBps,
                "--stress-spread-widen-bps", $FundingStressSpreadWidenBps,
                "--stress-funding-flip-bps", $FundingStressFundingFlipBps,
                "--stress-min-net-pnl-quote", $FundingStressMinNetPnlQuote,
                "--stress-max-drawdown-quote", $FundingStressMaxDrawdownQuote,
                "--sensitivity-spot-fee-bps", $FundingSensitivitySpotFeeBps,
                "--sensitivity-perp-fee-bps", $FundingSensitivityPerpFeeBps,
                "--sensitivity-slippage-bps", $FundingSensitivitySlippageBps,
                "--sensitivity-target-hold-intervals", $FundingSensitivityTargetHoldIntervals,
                "--sensitivity-max-break-even-hours", $FundingSensitivityMaxBreakEvenHours,
                "--oos-train-fraction", $FundingOosTrainFraction,
                "--oos-min-train-rows", $FundingOosMinTrainRows,
                "--oos-min-rows", $FundingOosMinRows,
                "--oos-min-train-span-hours", $FundingOosMinTrainSpanHours,
                "--oos-min-span-hours", $FundingOosMinSpanHours,
                "--walk-train-rows", $FundingWalkTrainRows,
                "--walk-test-rows", $FundingWalkTestRows,
                "--walk-step-rows", $FundingWalkStepRows,
                "--walk-min-windows", $FundingWalkMinWindows,
                "--walk-min-accepted-windows", $FundingWalkMinAcceptedWindows,
                "--walk-min-accepted-ratio", $FundingWalkMinAcceptedRatio,
                "--walk-min-train-span-hours", $FundingWalkMinTrainSpanHours,
                "--walk-min-test-span-hours", $FundingWalkMinTestSpanHours,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-required-row-fields", $FundingQualityRequiredRowFields,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence,
                "--min-forward-hours", $FundingPaperMinForwardHours,
                "--min-forward-rows", $FundingPaperMinForwardRows,
                "--min-forward-markets", $FundingPaperMinForwardMarkets
            )
            if ($FundingStress) {
                $argsList += @("--stress-enabled")
            }
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($FundingSensitivityOos) {
                $argsList += @("--sensitivity-oos")
            }
            if ($FundingSensitivityWalkForward) {
                $argsList += @("--sensitivity-walk-forward")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($ReportOutputPath) {
                $argsList += @("--rank-output", $ReportOutputPath)
            }
            if ($GridOutputPath) {
                $argsList += @("--backtest-output", $GridOutputPath)
            }
            if ($OosOutputPath) {
                $argsList += @("--oos-output", $OosOutputPath)
            }
            if ($WalkForwardOutputPath) {
                $argsList += @("--walk-forward-output", $WalkForwardOutputPath)
            }
            if ($FundingPlanPath) {
                $argsList += @("--paper-plan-output", $FundingPlanPath)
            }
            if ($PaperOutputPath) {
                $argsList += @("--paper-output", $PaperOutputPath)
            }
            if ($GateReportPath) {
                $argsList += @("--gate-report-output", $GateReportPath)
            }
            if ($RegimeReportPath) {
                $argsList += @("--regime-report-output", $RegimeReportPath)
            }
            if ($FrontierReportPath) {
                $argsList += @("--frontier-report-output", $FrontierReportPath)
            }
            if ($SensitivityReportPath) {
                $argsList += @("--sensitivity-output", $SensitivityReportPath)
            }
            if ($DecisionReportPath) {
                $argsList += @("--decision-report-output", $DecisionReportPath)
            }
            if ($DurationSec -gt 0) {
                $argsList += @(
                    "--wait-timeout-sec", $DurationSec,
                    "--wait-poll-interval-sec", $PollIntervalSec,
                    "--wait-stale-after-sec", $FundingStatusStaleAfterSec
                )
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-paper-plan" {
            if (-not $InputPath) {
                throw "funding-paper-plan requires -InputPath pointing to a funding-postprocess artifact"
            }
            if (-not $DecisionReportPath) {
                throw "funding-paper-plan requires -DecisionReportPath pointing to an accepted funding-decision-report artifact"
            }
            $argsList = @(
                "--config", $Config,
                "funding-paper-plan",
                "--postprocess", $InputPath,
                "--decision-report", $DecisionReportPath,
                "--min-forward-hours", $FundingPaperMinForwardHours,
                "--min-forward-rows", $FundingPaperMinForwardRows,
                "--min-forward-markets", $FundingPaperMinForwardMarkets
            )
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($PaperOutputPath) {
                $argsList += @("--paper-output", $PaperOutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-paper-forward" {
            if (-not $InputPath) {
                throw "funding-paper-forward requires -InputPath pointing to a forward funding JSONL dataset"
            }
            $planPath = if ($FundingPlanPath) { $FundingPlanPath } else { $PaperOutputPath }
            if (-not $planPath) {
                throw "funding-paper-forward requires -FundingPlanPath pointing to a funding-paper-plan artifact"
            }
            $argsList = @(
                "--config", $Config,
                "funding-paper-forward",
                "--plan", $planPath,
                "--input", $InputPath
            )
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($PaperSummaryOutputPath) {
                $argsList += @("--summary-output", $PaperSummaryOutputPath)
            }
            if ($FundingAllowSourceInput) {
                $argsList += @("--allow-source-input")
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-paper-decision-report" {
            if (-not $InputPath) {
                throw "funding-paper-decision-report requires -InputPath pointing to a funding-paper-forward summary artifact"
            }
            if (-not $FundingPlanPath) {
                throw "funding-paper-decision-report requires -FundingPlanPath pointing to the funding-paper-plan artifact"
            }
            $argsList = @(
                "--config", $Config,
                "funding-paper-decision-report",
                "--summary", $InputPath,
                "--plan", $FundingPlanPath
            )
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "funding-goal-audit" {
            $argsList = @(
                "--config", $Config,
                "funding-goal-audit",
                "--stale-after-sec", $FundingStatusStaleAfterSec,
                "--quality-min-rows", $FundingQualityMinRows,
                "--quality-min-markets", $FundingQualityMinMarkets,
                "--quality-min-completed-cycles", $FundingQualityMinCompletedCycles,
                "--quality-min-unique-cycles", $FundingQualityMinUniqueCycles,
                "--quality-min-avg-rows-per-cycle", $FundingQualityMinAvgRowsPerCycle,
                "--quality-min-min-rows-per-cycle", $FundingQualityMinMinRowsPerCycle,
                "--quality-max-error-rate", $FundingQualityMaxErrorRate,
                "--quality-max-cycle-market-duplicate-rate", $FundingQualityMaxCycleMarketDuplicateRate,
                "--quality-required-row-fields", $FundingQualityRequiredRowFields,
                "--quality-min-required-row-field-presence", $FundingQualityMinRequiredRowFieldPresence
            )
            if ($FundingStrictResearch) {
                $argsList += @("--strict-research")
            }
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($ManifestPath) {
                $argsList += @("--manifest", $ManifestPath)
            }
            if ($ReportOutputPath) {
                $argsList += @("--final-review", $ReportOutputPath)
            }
            if ($FundingPlanPath) {
                $argsList += @("--paper-plan", $FundingPlanPath)
            }
            if ($PaperSummaryOutputPath) {
                $argsList += @("--paper-summary", $PaperSummaryOutputPath)
            }
            if ($DecisionReportPath) {
                $argsList += @("--paper-decision", $DecisionReportPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "resolve-active-run" {
            if (-not $RunId) { throw "RunId is required for resolve-active-run" }
            $resolver = Join-Path $ProjectRoot "tools\resolve_active_run.ps1"
            if (-not (Test-Path -LiteralPath $resolver)) {
                throw "Active run resolver not found: $resolver"
            }
            & $resolver -RunId $RunId -RejectIncomplete -Reason $Reason
            if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            break
        }
        "fast-edge-membership-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $InputPath) { throw "InputPath is required for fast-edge-membership-plan (daily manifest JSON)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-plan" }
            $membershipScript = Join-Path $PSScriptRoot "src\gate_historical_membership_v1.py"
            Invoke-TradingMvpCli -ScriptPath $membershipScript -ArgsList @(
                "plan",
                "--daily-manifest", $InputPath,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-probe" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-probe" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-probe" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-probe" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-probe" }
            $membershipScript = Join-Path $PSScriptRoot "src\gate_historical_membership_v1.py"
            Invoke-TradingMvpCli -ScriptPath $membershipScript -ArgsList @(
                "probe",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v2-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $InputPath) { throw "InputPath is required for fast-edge-membership-v2-plan (daily manifest JSON)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v2-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-v2-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-v2-plan" }
            $membershipV2Script = Join-Path $PSScriptRoot "src\gate_historical_membership_v2.py"
            Invoke-TradingMvpCli -ScriptPath $membershipV2Script -ArgsList @(
                "plan",
                "--daily-manifest", $InputPath,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v2-probe" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-v2-probe" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-v2-probe" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v2-probe" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-v2-probe" }
            $membershipV2Script = Join-Path $PSScriptRoot "src\gate_historical_membership_v2.py"
            Invoke-TradingMvpCli -ScriptPath $membershipV2Script -ArgsList @(
                "probe",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v3-source-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $ClosurePath) { throw "ClosurePath is required for fast-edge-membership-v3-source-plan (membership-v2 closure manifest JSON)" }
            if (-not $InputPath) { throw "InputPath is required for fast-edge-membership-v3-source-plan (daily manifest JSON)" }
            if (-not $CoinRegistryPath) { throw "CoinRegistryPath is required for fast-edge-membership-v3-source-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v3-source-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-v3-source-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-v3-source-plan" }
            $membershipV3Script = Join-Path $PSScriptRoot "src\gate_historical_membership_v3.py"
            Invoke-TradingMvpCli -ScriptPath $membershipV3Script -ArgsList @(
                "plan",
                "--closure-manifest", $ClosurePath,
                "--daily-manifest", $InputPath,
                "--coin-registry", $CoinRegistryPath,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v3-source-probe" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-v3-source-probe" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-v3-source-probe" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v3-source-probe" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-v3-source-probe" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-v3-source-probe" }
            $membershipV3VisibleWrapper = Join-Path $ProjectRoot "tools\start_gate_historical_membership_v3_probe_visible.ps1"
            if (-not (Test-Path -LiteralPath $membershipV3VisibleWrapper -PathType Leaf)) {
                throw "Visible membership-v3 wrapper not found: $membershipV3VisibleWrapper"
            }
            $visibleCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$membershipV3VisibleWrapper`" -PlanPath `"$PlanPath`" -ExpectedPlanHash `"$ExpectedPlanHash`" -OutputPath `"$OutputPath`" -RunId `"$RunId`" -MaxRuntimeSec $MaxRuntimeSec -ConfirmedPublicProbe"
            throw "Direct membership-v3 network execution is disabled. Launch the approved probe through the visible owned wrapper: $visibleCommand"
        }
        "fast-edge-membership-history-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-history-plan (accepted probe report JSON)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-history-plan" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-history-plan" }
            if (-not $InputPath) { throw "InputPath is required for fast-edge-membership-history-plan (daily manifest JSON)" }
            if (-not $CoinRegistryPath) { throw "CoinRegistryPath is required for fast-edge-membership-history-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-history-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-history-plan" }
            if ($MaxRuntimeSec -gt 7200) { throw "MaxRuntimeSec must be <= 7200 for fast-edge-membership-history-plan" }
            $historyPlanScript = Join-Path $PSScriptRoot "src\gate_historical_membership_history_plan.py"
            Invoke-TradingMvpCli -ScriptPath $historyPlanScript -ArgsList @(
                "--probe-report", $PlanPath,
                "--expected-probe-plan-hash", $ExpectedPlanHash,
                "--expected-probe-artifact-hash", $ExpectedArtifactHash,
                "--daily-manifest", $InputPath,
                "--coin-registry", $CoinRegistryPath,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-history-collect" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-history-collect" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-history-collect" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-history-collect (archive root)" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-history-collect" }
            if ($MaxRuntimeSec -gt 7200) { throw "MaxRuntimeSec must be <= 7200 for fast-edge-membership-history-collect" }
            $historyCollectorScript = Join-Path $PSScriptRoot "src\gate_historical_membership_history_collector.py"
            Invoke-TradingMvpCli -ScriptPath $historyCollectorScript -ArgsList @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output-root", $OutputPath,
                "--manifest", $ManifestPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-history-quality" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-history-quality" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-history-quality" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-history-quality (collector manifest)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-history-quality (collector artifact hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-history-quality (normalized root)" }
            if (-not $QualityReportPath) { throw "QualityReportPath is required for fast-edge-membership-history-quality" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-history-quality" }
            $historyQualityScript = Join-Path $PSScriptRoot "src\gate_historical_membership_history_quality.py"
            Invoke-TradingMvpCli -ScriptPath $historyQualityScript -ArgsList @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--collect-manifest", $ManifestPath,
                "--expected-collect-artifact-hash", $ExpectedArtifactHash,
                "--output-root", $OutputPath,
                "--report", $QualityReportPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v3-history-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-v3-history-plan (accepted source probe report JSON)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-v3-history-plan" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-v3-history-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v3-history-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-v3-history-plan" }
            if ($MaxRuntimeSec -gt 7200) { throw "MaxRuntimeSec must be <= 7200 for fast-edge-membership-v3-history-plan" }
            $membershipV3HistoryPlan = Join-Path $PSScriptRoot "src\gate_historical_membership_v3_history_plan.py"
            Invoke-TradingMvpCli -ScriptPath $membershipV3HistoryPlan -ArgsList @(
                "--source-probe-report", $PlanPath,
                "--expected-source-plan-hash", $ExpectedPlanHash,
                "--expected-source-artifact-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v3-history-collect" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-v3-history-collect" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-v3-history-collect" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v3-history-collect (archive root)" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-v3-history-collect" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-v3-history-collect" }
            if ($MaxRuntimeSec -gt 7200) { throw "MaxRuntimeSec must be <= 7200 for fast-edge-membership-v3-history-collect" }
            $membershipV3HistoryVisibleWrapper = Join-Path $ProjectRoot "tools\start_gate_historical_membership_v3_history_collect_visible.ps1"
            if (-not (Test-Path -LiteralPath $membershipV3HistoryVisibleWrapper -PathType Leaf)) {
                throw "Visible membership-v3 history wrapper not found: $membershipV3HistoryVisibleWrapper"
            }
            $visibleCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$membershipV3HistoryVisibleWrapper`" -PlanPath `"$PlanPath`" -ExpectedPlanHash `"$ExpectedPlanHash`" -OutputRoot `"$OutputPath`" -ManifestPath `"$ManifestPath`" -RunId `"$RunId`" -MaxRuntimeSec $MaxRuntimeSec -ConfirmedPublicHistoryCollect"
            throw "Direct membership-v3 history network execution is disabled. Launch the approved collect through the visible owned wrapper: $visibleCommand"
        }
        "fast-edge-membership-v3-history-quality-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-v3-history-quality-plan (history PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-v3-history-quality-plan (history plan hash)" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-v3-history-quality-plan (collector manifest)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-v3-history-quality-plan (collector artifact hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v3-history-quality-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-v3-history-quality-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-v3-history-quality-plan" }
            $membershipV3HistoryQuality = Join-Path $PSScriptRoot "src\gate_historical_membership_v3_history_quality.py"
            Invoke-TradingMvpCli -ScriptPath $membershipV3HistoryQuality -ArgsList @(
                "plan",
                "--history-plan", $PlanPath,
                "--expected-history-plan-hash", $ExpectedPlanHash,
                "--collect-manifest", $ManifestPath,
                "--expected-collect-artifact-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-v3-history-quality" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-v3-history-quality (quality PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-v3-history-quality" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-v3-history-quality (normalized root)" }
            if (-not $QualityReportPath) { throw "QualityReportPath is required for fast-edge-membership-v3-history-quality" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-v3-history-quality" }
            $membershipV3HistoryQuality = Join-Path $PSScriptRoot "src\gate_historical_membership_v3_history_quality.py"
            Invoke-TradingMvpCli -ScriptPath $membershipV3HistoryQuality -ArgsList @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output-root", $OutputPath,
                "--report", $QualityReportPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-train-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-train-plan (accepted quality report)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-train-plan (quality artifact hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-train-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-train-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-train-plan" }
            $membershipMomentumScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_train.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumScript -ArgsList @(
                "plan",
                "--quality-report", $PlanPath,
                "--expected-quality-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-train" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-train" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-train" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-train" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-train" }
            $membershipMomentumScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_train.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumScript -ArgsList @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-v2-train-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-train-plan (accepted v3 quality report)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-train-plan (quality artifact hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-train-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-train-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-train-plan" }
            $membershipMomentumV2Script = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_train.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2Script -ArgsList @(
                "plan",
                "--quality-report", $PlanPath,
                "--expected-quality-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-v2-train" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-train" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-train" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-train" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-train" }
            $membershipMomentumV2Script = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_train.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2Script -ArgsList @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-v2-oos-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-oos-plan (accepted v3 quality report)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-oos-plan (quality artifact hash)" }
            if (-not $TrainPlanPath) { throw "TrainPlanPath is required for fast-edge-membership-momentum-v2-oos-plan" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-oos-plan (train plan hash)" }
            if (-not $FeasibilityPath) { throw "FeasibilityPath is required for fast-edge-membership-momentum-v2-oos-plan (feasible train result)" }
            if (-not $ExpectedFeasibilityResultHash) { throw "ExpectedFeasibilityResultHash is required for fast-edge-membership-momentum-v2-oos-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-oos-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-oos-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-oos-plan" }
            $membershipMomentumV2OosScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_oos.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2OosScript -ArgsList @(
                "plan",
                "--quality-report", $PlanPath,
                "--expected-quality-hash", $ExpectedArtifactHash,
                "--train-plan", $TrainPlanPath,
                "--expected-train-plan-hash", $ExpectedPlanHash,
                "--train-result", $FeasibilityPath,
                "--expected-train-result-hash", $ExpectedFeasibilityResultHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-v2-oos" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-oos" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-oos" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-oos" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-oos" }
            $membershipMomentumV2OosScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_oos.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2OosScript -ArgsList @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-v2-execution-probe-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-probe-plan (accepted OOS plan)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-execution-probe-plan (OOS plan hash)" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-execution-probe-plan (accepted OOS result)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-execution-probe-plan (OOS result hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-execution-probe-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-execution-probe-plan" }
            if ($NotBeforeDay -le 0) { throw "NotBeforeDay must be a positive UTC epoch day for fast-edge-membership-momentum-v2-execution-probe-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-execution-probe-plan" }
            $membershipMomentumV2ProbeScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_probe.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2ProbeScript -ArgsList @(
                "plan",
                "--oos-plan", $PlanPath,
                "--expected-oos-plan-hash", $ExpectedPlanHash,
                "--oos-result", $EvaluationPath,
                "--expected-oos-result-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--not-before-day", $NotBeforeDay
            )
            break
        }
        "fast-edge-membership-momentum-v2-execution-probe-validate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-probe-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-execution-probe-validate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-execution-probe-validate" }
            $membershipMomentumV2ProbeScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_probe.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2ProbeScript -ArgsList @(
                "validate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            break
        }
        "fast-edge-membership-momentum-v2-market-snapshot-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-market-snapshot-plan (execution-probe PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-market-snapshot-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-market-snapshot-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-market-snapshot-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-momentum-v2-market-snapshot-plan" }
            $marketSnapshotScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_market_snapshot.py"
            Invoke-TradingMvpCli -ScriptPath $marketSnapshotScript -ArgsList @(
                "plan",
                "--probe-plan", $PlanPath,
                "--expected-probe-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-v2-market-snapshot-collect" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-market-snapshot-collect" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-market-snapshot-collect" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-market-snapshot-collect" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-market-snapshot-collect" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-membership-momentum-v2-market-snapshot-collect" }
            $marketSnapshotWrapper = Join-Path $ProjectRoot "tools\start_gate_membership_momentum_v2_market_snapshot_visible.ps1"
            if (-not (Test-Path -LiteralPath $marketSnapshotWrapper -PathType Leaf)) {
                throw "Visible momentum-v2 market snapshot wrapper not found: $marketSnapshotWrapper"
            }
            $visibleCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$marketSnapshotWrapper`" -PlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -OutputPath `"$OutputPath`" -RunId $RunId -MaxRuntimeSec $MaxRuntimeSec -ConfirmedPublicMarketSnapshotCollect"
            throw "Direct market-snapshot network execution is disabled. Launch the exact-approved collect through the visible wrapper: $visibleCommand"
        }
        "fast-edge-membership-momentum-v2-execution-selection" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-selection (probe PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-execution-selection (probe plan hash)" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-momentum-v2-execution-selection (daily market snapshot)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-execution-selection (snapshot hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-execution-selection" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-execution-selection" }
            $membershipMomentumV2SelectionScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_selection.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2SelectionScript -ArgsList @(
                "select",
                "--probe-plan", $PlanPath,
                "--expected-probe-plan-hash", $ExpectedPlanHash,
                "--market-snapshot-manifest", $ManifestPath,
                "--expected-market-snapshot-hash", $ExpectedArtifactHash,
                "--output", $OutputPath
            )
            break
        }
        "fast-edge-membership-momentum-v2-execution-selection-validate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-selection-validate (selection artifact)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-execution-selection-validate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-execution-selection-validate" }
            $membershipMomentumV2SelectionScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_selection.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumV2SelectionScript -ArgsList @(
                "validate",
                "--selection", $PlanPath,
                "--expected-artifact-hash", $ExpectedArtifactHash
            )
            break
        }
        "fast-edge-membership-momentum-v2-execution-probe-window-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-probe-window-plan (probe PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-execution-probe-window-plan (probe plan hash)" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-execution-probe-window-plan (causal selection)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-execution-probe-window-plan (selection hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-execution-probe-window-plan" }
            if (-not $SamplesPath) { throw "SamplesPath is required for fast-edge-membership-momentum-v2-execution-probe-window-plan" }
            if (-not $WindowManifestPath) { throw "WindowManifestPath is required for fast-edge-membership-momentum-v2-execution-probe-window-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-execution-probe-window-plan" }
            if ($MaxRuntimeSec -lt 1200 -or $MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be in [1200, 1800] for fast-edge-membership-momentum-v2-execution-probe-window-plan" }
            $runtimeScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_probe_runtime.py"
            Invoke-TradingMvpCli -ScriptPath $runtimeScript -ArgsList @(
                "plan-window",
                "--probe-plan", $PlanPath,
                "--expected-probe-plan-hash", $ExpectedPlanHash,
                "--selection", $EvaluationPath,
                "--expected-selection-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--samples", $SamplesPath,
                "--manifest", $WindowManifestPath,
                "--run-id", $RunId,
                "--window-index", $WindowIndex,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--workers", $ProbeWorkers
            )
            break
        }
        "fast-edge-membership-momentum-v2-execution-probe-collect" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-probe-collect (window PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-execution-probe-collect (window plan hash)" }
            if ($MaxRuntimeSec -lt 1200 -or $MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be in [1200, 1800] for fast-edge-membership-momentum-v2-execution-probe-collect" }
            $visibleWrapper = Join-Path $ProjectRoot "tools\start_gate_membership_momentum_v2_execution_probe_visible.ps1"
            if (-not (Test-Path -LiteralPath $visibleWrapper -PathType Leaf)) {
                throw "Visible momentum-v2 execution-probe wrapper not found: $visibleWrapper"
            }
            $visibleCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$visibleWrapper`" -WindowPlanPath `"$PlanPath`" -ExpectedPlanHash $ExpectedPlanHash -MaxRuntimeSec $MaxRuntimeSec -ConfirmedPublicExecutionProbe"
            throw "Direct execution-probe network execution is disabled. Launch the exact-approved window through the visible wrapper: $visibleCommand"
        }
        "fast-edge-membership-momentum-v2-execution-probe-evaluate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-execution-probe-evaluate (probe PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-execution-probe-evaluate (probe plan hash)" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-execution-probe-evaluate (causal selection)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-execution-probe-evaluate (selection hash)" }
            if (-not $ProbeManifestPaths) { throw "ProbeManifestPaths is required for fast-edge-membership-momentum-v2-execution-probe-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-execution-probe-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-execution-probe-evaluate" }
            $runtimeScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_probe_runtime.py"
            Invoke-TradingMvpCli -ScriptPath $runtimeScript -ArgsList @(
                "evaluate",
                "--probe-plan", $PlanPath,
                "--expected-probe-plan-hash", $ExpectedPlanHash,
                "--selection", $EvaluationPath,
                "--expected-selection-hash", $ExpectedArtifactHash,
                "--manifests", $ProbeManifestPaths,
                "--output", $OutputPath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-paper-plan (PAPER_FORWARD_READY execution report)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-paper-plan (execution report result hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-paper-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-plan" }
            $paperPlanScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_plan.py"
            Invoke-TradingMvpCli -ScriptPath $paperPlanScript -ArgsList @(
                "plan",
                "--execution-report", $EvaluationPath,
                "--expected-execution-report-hash", $ExpectedArtifactHash,
                "--output", $OutputPath,
                "--run-id", $RunId
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-validate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-validate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-validate" }
            $paperPlanScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_plan.py"
            Invoke-TradingMvpCli -ScriptPath $paperPlanScript -ArgsList @(
                "validate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-approve" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-approve" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-approve" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-approve" }
            if (-not $ConfirmedPaperForward) { throw "ConfirmedPaperForward is required for fast-edge-membership-momentum-v2-paper-approve" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-approve" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "approve",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--confirmed-paper-forward"
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-init" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-init" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-init" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-init" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-membership-momentum-v2-paper-init" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-membership-momentum-v2-paper-init" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-init" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "init",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-execution-window-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-execution-window-plan (paper PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-paper-execution-window-plan (causal selection)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-paper-execution-window-plan (selection hash)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            if (-not $SamplesPath) { throw "SamplesPath is required for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            if (-not $WindowManifestPath) { throw "WindowManifestPath is required for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            if ($MaxRuntimeSec -lt 1200 -or $MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be in [1200, 1800] for fast-edge-membership-momentum-v2-paper-execution-window-plan" }
            $runtimeScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_execution_probe_runtime.py"
            Invoke-TradingMvpCli -ScriptPath $runtimeScript -ArgsList @(
                "plan-paper-window",
                "--paper-plan", $PlanPath,
                "--expected-paper-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--selection", $EvaluationPath,
                "--expected-selection-hash", $ExpectedArtifactHash,
                "--boundary", $PaperBoundary,
                "--output", $OutputPath,
                "--samples", $SamplesPath,
                "--manifest", $WindowManifestPath,
                "--run-id", $RunId,
                "--window-index", $WindowIndex,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--workers", $ProbeWorkers
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-execution-raw" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-execution-raw (paper PlanOnly)" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-execution-raw" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-execution-raw" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-paper-execution-raw (causal selection)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-paper-execution-raw (selection hash)" }
            if (-not $ProbeManifestPaths) { throw "ProbeManifestPaths is required for fast-edge-membership-momentum-v2-paper-execution-raw" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-execution-raw (raw input)" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-momentum-v2-paper-execution-raw (raw manifest)" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-execution-raw" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            $manifestArgs = @()
            $manifestValues = @(
                $ProbeManifestPaths.Split(",") |
                    ForEach-Object { $_.Trim() } |
                    Where-Object { $_ }
            )
            if ($manifestValues.Count -ne 3) { throw "ProbeManifestPaths must contain exactly three paper execution window manifests" }
            foreach ($value in $manifestValues) { $manifestArgs += @("--window-manifest", $value) }
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "build-execution-raw",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--selection", $EvaluationPath,
                "--expected-selection-hash", $ExpectedArtifactHash,
                "--boundary", $PaperBoundary,
                $manifestArgs,
                "--raw-input-output", $OutputPath,
                "--raw-manifest-output", $ManifestPath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-funding-raw" {
            Assert-BasisActionGate -OfflineWork
            if (-not $EntrySourcePath) { throw "EntrySourcePath is required for fast-edge-membership-momentum-v2-paper-funding-raw" }
            if (-not $ExpectedEntrySourceHash) { throw "ExpectedEntrySourceHash is required for fast-edge-membership-momentum-v2-paper-funding-raw" }
            if (-not $ExitSourcePath) { throw "ExitSourcePath is required for fast-edge-membership-momentum-v2-paper-funding-raw" }
            if (-not $ExpectedExitSourceHash) { throw "ExpectedExitSourceHash is required for fast-edge-membership-momentum-v2-paper-funding-raw" }
            if (-not $FundingHistoryPaths) { throw "FundingHistoryPaths is required for fast-edge-membership-momentum-v2-paper-funding-raw" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-funding-raw (raw input)" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-membership-momentum-v2-paper-funding-raw (raw manifest)" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-funding-raw" }
            $historyPaths = @(
                $FundingHistoryPaths.Split(",") |
                    ForEach-Object { $_.Trim() } |
                    Where-Object { $_ }
            )
            if ($historyPaths.Count -lt 1) {
                throw "FundingHistoryPaths must contain at least one funding history artifact"
            }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            $argsList = @(
                "build-funding-raw",
                "--entry-source", $EntrySourcePath,
                "--expected-entry-source-hash", $ExpectedEntrySourceHash,
                "--exit-source", $ExitSourcePath,
                "--expected-exit-source-hash", $ExpectedExitSourceHash,
                "--raw-input-output", $OutputPath,
                "--raw-manifest-output", $ManifestPath
            )
            foreach ($historyPath in $historyPaths) {
                $argsList += @("--funding-history", $historyPath)
            }
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList $argsList
            break
        }
        "fast-edge-membership-momentum-v2-paper-source" {
            Assert-BasisActionGate -OfflineWork
            if (-not $ObservationPath) { throw "ObservationPath is required for fast-edge-membership-momentum-v2-paper-source (raw manifest)" }
            if (-not $ExpectedRawManifestHash) { throw "ExpectedRawManifestHash is required for fast-edge-membership-momentum-v2-paper-source" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-source" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-source" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "build-source",
                "--raw-manifest", $ObservationPath,
                "--expected-raw-manifest-hash", $ExpectedRawManifestHash,
                "--output", $OutputPath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-evidence" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-evidence" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-evidence" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-evidence" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-paper-evidence (causal selection)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-paper-evidence (selection hash)" }
            if (-not $ProbeManifestPaths) { throw "ProbeManifestPaths is required for fast-edge-membership-momentum-v2-paper-evidence" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-evidence" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-evidence" }
            $sourcePaths = @(
                $ProbeManifestPaths.Split(",") |
                    ForEach-Object { $_.Trim() } |
                    Where-Object { $_ }
            )
            if ($sourcePaths.Count -ne 3) {
                throw "ProbeManifestPaths must contain exactly three source artifacts: entry, exit, funding"
            }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            $argsList = @(
                "build-evidence",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--selection", $EvaluationPath,
                "--expected-selection-hash", $ExpectedArtifactHash,
                "--output", $OutputPath
            )
            foreach ($sourcePath in $sourcePaths) {
                $argsList += @("--source", $sourcePath)
            }
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList $argsList
            break
        }
        "fast-edge-membership-momentum-v2-paper-event" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-event" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-event" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-event" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-membership-momentum-v2-paper-event (causal selection)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-paper-event (selection hash)" }
            if (-not $ObservationPath) { throw "ObservationPath is required for fast-edge-membership-momentum-v2-paper-event (execution/funding evidence)" }
            if (-not $ExpectedEvidenceHash) { throw "ExpectedEvidenceHash is required for fast-edge-membership-momentum-v2-paper-event" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-v2-paper-event" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-event" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "build-event",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--selection", $EvaluationPath,
                "--expected-selection-hash", $ExpectedArtifactHash,
                "--evidence", $ObservationPath,
                "--expected-evidence-hash", $ExpectedEvidenceHash,
                "--output", $OutputPath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-apply" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-apply" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-apply" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-apply" }
            if (-not $ObservationPath) { throw "ObservationPath is required for fast-edge-membership-momentum-v2-paper-apply (paper event)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-v2-paper-apply (event hash)" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-membership-momentum-v2-paper-apply" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-membership-momentum-v2-paper-apply" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-apply" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "apply",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--event", $ObservationPath,
                "--expected-event-hash", $ExpectedArtifactHash,
                "--ledger", $LedgerPath,
                "--state", $StatePath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-status" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-status" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-status" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-status" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-membership-momentum-v2-paper-status" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-membership-momentum-v2-paper-status" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-status" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "status",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath
            )
            break
        }
        "fast-edge-membership-momentum-v2-paper-incident" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-v2-paper-incident" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-v2-paper-incident" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-membership-momentum-v2-paper-incident" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-membership-momentum-v2-paper-incident" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-membership-momentum-v2-paper-incident" }
            if (-not $Reason) { throw "Reason is required for fast-edge-membership-momentum-v2-paper-incident" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-v2-paper-incident" }
            $paperStateScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_v2_paper_state.py"
            Invoke-TradingMvpCli -ScriptPath $paperStateScript -ArgsList @(
                "incident",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval", $PaperApprovalPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath,
                "--incident-type", $PaperIncidentType,
                "--reason", $Reason
            )
            break
        }
        "fast-edge-membership-momentum-oos-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-oos-plan (accepted quality report)" }
            if (-not $ExpectedArtifactHash) { throw "ExpectedArtifactHash is required for fast-edge-membership-momentum-oos-plan (quality artifact hash)" }
            if (-not $TrainPlanPath) { throw "TrainPlanPath is required for fast-edge-membership-momentum-oos-plan" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-oos-plan (train plan hash)" }
            if (-not $FeasibilityPath) { throw "FeasibilityPath is required for fast-edge-membership-momentum-oos-plan (feasible train result)" }
            if (-not $ExpectedFeasibilityResultHash) { throw "ExpectedFeasibilityResultHash is required for fast-edge-membership-momentum-oos-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-oos-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-membership-momentum-oos-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-oos-plan" }
            $membershipMomentumOosScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_oos.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumOosScript -ArgsList @(
                "plan",
                "--quality-report", $PlanPath,
                "--expected-quality-hash", $ExpectedArtifactHash,
                "--train-plan", $TrainPlanPath,
                "--expected-train-plan-hash", $ExpectedPlanHash,
                "--train-result", $FeasibilityPath,
                "--expected-train-result-hash", $ExpectedFeasibilityResultHash,
                "--output", $OutputPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-membership-momentum-oos" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-membership-momentum-oos" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-membership-momentum-oos" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-membership-momentum-oos" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-oos" }
            $membershipMomentumOosScript = Join-Path $PSScriptRoot "src\gate_membership_momentum_oos.py"
            Invoke-TradingMvpCli -ScriptPath $membershipMomentumOosScript -ArgsList @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            break
        }
        "fast-edge-basis-universe-build" {
            Assert-BasisActionGate
            if (-not $InputPath) { throw "InputPath is required for fast-edge-basis-universe-build (PIT universe_state.json)" }
            if (-not $CoinRegistryPath) { throw "CoinRegistryPath is required for fast-edge-basis-universe-build" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-universe-build" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-universe-build" }
            $codeSnapshot = New-BasisCodeSnapshot
            $basisGate = if ($ActiveRunGatePath) { $ActiveRunGatePath } else { Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
            $argsList = @(
                "--pit-state", $InputPath,
                "--coin-registry", $CoinRegistryPath,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--active-run-gate", $basisGate,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            if ($RunId) { $argsList += @("--run-id", $RunId) }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_universe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $InputPath) { throw "InputPath is required for fast-edge-basis-plan (canonical universe JSON)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-plan" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "plan",
                "--universe", $InputPath,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_edge.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-history-collect" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-history-collect" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-history-collect" }
            if ($MaxRuntimeSec -gt 7200) { throw "MaxRuntimeSec must be <= 7200 for fast-edge-basis-history-collect" }
            $codeSnapshot = New-BasisCodeSnapshot
            $basisOutputRoot = if ($OutputPath) { $OutputPath } else { "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis" }
            $basisGate = if ($ActiveRunGatePath) { $ActiveRunGatePath } else { Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output-root", $basisOutputRoot,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--active-run-gate", $basisGate,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            if ($RunId) { $argsList += @("--run-id", $RunId) }
            if ($ParallelParentRunId) { $argsList += @("--parallel-parent-run-id", $ParallelParentRunId) }
            if ($Resume) { $argsList += "--resume" }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_collector.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-history-quality" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-history-quality" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-history-quality" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-history-quality" }
            if (-not $OutputPath) { throw "OutputPath is required for normalized basis JSONL" }
            if (-not $ReportOutputPath) { throw "ReportOutputPath is required for basis quality report" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-history-quality" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--manifest", $ManifestPath,
                "--normalized-output", $OutputPath,
                "--report-output", $ReportOutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_quality.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-evaluate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-evaluate" }
            if (-not $QualityReportPath) { throw "QualityReportPath is required for fast-edge-basis-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-evaluate" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--quality-report", $QualityReportPath,
                "--output", $OutputPath,
                "--stage", $PitPlanStage,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            if ($PitPlanStage -eq "full_evaluation") {
                if (-not $FeasibilityPath) { throw "FeasibilityPath is required for full_evaluation" }
                $argsList += @("--feasibility", $FeasibilityPath)
            } elseif ($FeasibilityPath) {
                throw "FeasibilityPath is not allowed for train_feasibility"
            }
            if ($ParallelParentRunId) { $argsList += @("--parallel-parent-run-id", $ParallelParentRunId) }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_evaluator.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-probe-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-basis-probe-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-probe-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-probe-plan" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @("plan", "--evaluation", $EvaluationPath, "--output", $OutputPath)
            if ($FirstProbeWindowStartUtc) { $argsList += @("--first-window-start-utc", $FirstProbeWindowStartUtc) }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_probe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-probe" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-probe" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-probe" }
            if (-not $OutputPath) { throw "OutputPath is required for probe samples JSONL" }
            if (-not $ManifestPath) { throw "ManifestPath is required for probe manifest" }
            if ($MaxRuntimeSec -lt 1200 -or $MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be in [1200, 1800] for fast-edge-basis-probe" }
            $codeSnapshot = New-BasisCodeSnapshot
            $basisGate = if ($ActiveRunGatePath) { $ActiveRunGatePath } else { Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
            $argsList = @(
                "collect",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--window-index", $WindowIndex,
                "--samples", $OutputPath,
                "--manifest", $ManifestPath,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--active-run-gate", $basisGate,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_probe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-report" {
            Assert-BasisActionGate -OfflineWork
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-basis-report" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-report" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-report" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @("report", "--evaluation", $EvaluationPath, "--output", $OutputPath)
            if ($ProbePlanPath) { $argsList += @("--probe-plan", $ProbePlanPath) }
            if ($ProbeManifestPaths) { $argsList += @("--manifests", $ProbeManifestPaths) }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_probe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-paper-init" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-paper-init" }
            if (-not $SprintReportPath) { throw "SprintReportPath is required for fast-edge-basis-paper-init" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-basis-paper-init" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-basis-paper-init" }
            $argsList = @(
                "init",
                "--plan", $PlanPath,
                "--report", $SprintReportPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath,
                "--daily-loss-limit-quote", $DailyLossLimitQuote
            )
            Invoke-TradingMvpCli -ScriptPath $basisPaperOmsCli -ArgsList $argsList
            break
        }
        "fast-edge-basis-paper-observe" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-paper-observe" }
            if (-not $SprintReportPath) { throw "SprintReportPath is required for fast-edge-basis-paper-observe" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-basis-paper-observe" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-basis-paper-observe" }
            if (-not $ObservationPath) { throw "ObservationPath is required for fast-edge-basis-paper-observe" }
            $argsList = @(
                "observe",
                "--plan", $PlanPath,
                "--report", $SprintReportPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath,
                "--observation", $ObservationPath
            )
            Invoke-TradingMvpCli -ScriptPath $basisPaperOmsCli -ArgsList $argsList
            break
        }
        "fast-edge-basis-paper-status" {
            Assert-BasisActionGate -OfflineWork
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-basis-paper-status" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-basis-paper-status" }
            $argsList = @("status", "--ledger", $LedgerPath, "--state", $StatePath)
            Invoke-TradingMvpCli -ScriptPath $basisPaperOmsCli -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-preflight" {
            Assert-BasisActionGate
            if (-not $InputPath) { throw "InputPath is required for fast-edge-basis-v2-preflight (PIT universe_state.json)" }
            if (-not $CoinRegistryPath) { throw "CoinRegistryPath is required for fast-edge-basis-v2-preflight" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-v2-preflight (daily cache manifest)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-preflight" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-preflight" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--pit-state", $InputPath,
                "--coin-registry", $CoinRegistryPath,
                "--daily-cache-manifest", $ManifestPath,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_preflight.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $InputPath) { throw "InputPath is required for fast-edge-basis-v2-plan (accepted preflight artifact)" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-v2-plan" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "plan",
                "--preflight", $InputPath,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-cache-audit" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-cache-audit" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-cache-audit" }
            if (-not $InputPath) { throw "InputPath is required for fast-edge-basis-v2-cache-audit cache root" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-cache-audit report" }
            if ($MaxRuntimeSec -gt 300) { throw "MaxRuntimeSec must be <= 300 for fast-edge-basis-v2-cache-audit" }
            $codeSnapshot = New-BasisCodeSnapshot
            $basisOutputRoot = $InputPath
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output-root", $basisOutputRoot,
                "--report-output", $OutputPath,
                "--code-snapshot-dir", $codeSnapshot.snapshot_path,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            Invoke-TradingMvpCli -ScriptPath $historicalBasisV2CacheAuditCli -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-history-collect" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-history-collect" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-history-collect" }
            if ($MaxRuntimeSec -gt 5400) { throw "MaxRuntimeSec must be <= 5400 for fast-edge-basis-v2-history-collect" }
            $codeSnapshot = New-BasisCodeSnapshot
            $basisOutputRoot = if ($OutputPath) { $OutputPath } else { "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2" }
            $basisGate = if ($ActiveRunGatePath) { $ActiveRunGatePath } else { Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output-root", $basisOutputRoot,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--active-run-gate", $basisGate,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            if ($RunId) { $argsList += @("--run-id", $RunId) }
            if ($Resume) { $argsList += "--resume" }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_collector.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-history-quality" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-history-quality" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-history-quality" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-v2-history-quality" }
            if (-not $OutputPath) { throw "OutputPath is required for normalized v2 candles JSONL" }
            if (-not $FundingOutputPath) { throw "FundingOutputPath is required for v2 funding events JSONL" }
            if (-not $ReportOutputPath) { throw "ReportOutputPath is required for v2 quality report" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-history-quality" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--manifest", $ManifestPath,
                "--candles-output", $OutputPath,
                "--funding-output", $FundingOutputPath,
                "--report-output", $ReportOutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_quality.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-train-postprocess" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-train-postprocess" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-train-postprocess" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-v2-train-postprocess" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-train-postprocess" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-train-postprocess" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--collector-manifest", $ManifestPath,
                "--output-root", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            if ($PlanOnly) { $argsList += "--plan-only" }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_postprocess.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-oos-postprocess" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-oos-postprocess" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-oos-postprocess" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-v2-oos-postprocess" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-oos-postprocess" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-oos-postprocess" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--train-postprocess-manifest", $ManifestPath,
                "--output-root", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            if ($PlanOnly) { $argsList += "--plan-only" }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_oos_postprocess.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-evaluate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-evaluate" }
            if (-not $QualityReportPath) { throw "QualityReportPath is required for fast-edge-basis-v2-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-evaluate" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--quality-report", $QualityReportPath,
                "--output", $OutputPath,
                "--stage", $PitPlanStage,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            if ($PitPlanStage -eq "full_evaluation") {
                if (-not $FeasibilityPath) { throw "FeasibilityPath is required for v2 full_evaluation" }
                $argsList += @("--feasibility", $FeasibilityPath)
            } elseif ($FeasibilityPath) {
                throw "FeasibilityPath is not allowed for v2 train_feasibility"
            }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_evaluator.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-report" {
            Assert-BasisActionGate -OfflineWork
            $hasEvaluation = -not [string]::IsNullOrWhiteSpace($EvaluationPath)
            $hasClosure = -not [string]::IsNullOrWhiteSpace($ClosurePath)
            if ($hasEvaluation -eq $hasClosure) {
                throw "Exactly one of EvaluationPath or ClosurePath is required for fast-edge-basis-v2-report"
            }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-report" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-report" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @("--output", $OutputPath)
            if ($hasEvaluation) {
                $argsList += @("--evaluation", $EvaluationPath)
            } else {
                $argsList += @("--closure-manifest", $ClosurePath)
            }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_report.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-execution-probe-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-basis-v2-execution-probe-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-execution-probe-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-v2-execution-probe-plan" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @("plan", "--evaluation", $EvaluationPath, "--output", $OutputPath)
            if ($FirstProbeWindowStartUtc) { $argsList += @("--first-window-start-utc", $FirstProbeWindowStartUtc) }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_execution_probe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-execution-probe" {
            Assert-BasisActionGate
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-execution-probe" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-execution-probe" }
            if (-not $OutputPath) { throw "OutputPath is required for v2 probe samples JSONL" }
            if (-not $ManifestPath) { throw "ManifestPath is required for v2 probe manifest" }
            if ($MaxRuntimeSec -lt 1200 -or $MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be in [1200, 1800] for fast-edge-basis-v2-execution-probe" }
            $codeSnapshot = New-BasisCodeSnapshot
            $basisGate = if ($ActiveRunGatePath) { $ActiveRunGatePath } else { Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
            $argsList = @(
                "collect",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--window-index", $WindowIndex,
                "--samples", $OutputPath,
                "--manifest", $ManifestPath,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--active-run-gate", $basisGate,
                "--code-snapshot-hash", $codeSnapshot.code_snapshot_hash,
                "--code-snapshot-manifest", $codeSnapshot.manifest_path
            )
            if ($RunId) { $argsList += @("--run-id", $RunId) }
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_execution_probe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-execution-probe-evaluate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-basis-v2-execution-probe-evaluate" }
            if (-not $ProbePlanPath) { throw "ProbePlanPath is required for fast-edge-basis-v2-execution-probe-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-execution-probe-evaluate" }
            if (-not $ProbeManifestPaths) { throw "ProbeManifestPaths is required for fast-edge-basis-v2-execution-probe-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-execution-probe-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-execution-probe-evaluate" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "evaluate",
                "--evaluation", $EvaluationPath,
                "--plan", $ProbePlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--manifests", $ProbeManifestPaths,
                "--output", $OutputPath
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_execution_probe.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $InputPath) { throw "InputPath is required for fast-edge-basis-v2-paper-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-basis-v2-paper-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-v2-paper-plan" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @("plan", "--probe-report", $InputPath, "--output", $OutputPath)
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_paper_oms.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-init" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-paper-init" }
            if (-not $SprintReportPath) { throw "SprintReportPath is required for fast-edge-basis-v2-paper-init" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-basis-v2-paper-init" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-basis-v2-paper-init" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-v2-paper-init" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "init",
                "--plan", $PlanPath,
                "--probe-report", $SprintReportPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath,
                "--daily-loss-limit-quote", $DailyLossLimitQuote
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_paper_oms.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-observe" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-paper-observe" }
            if (-not $SprintReportPath) { throw "SprintReportPath is required for fast-edge-basis-v2-paper-observe" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-basis-v2-paper-observe" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-basis-v2-paper-observe" }
            if (-not $ObservationPath) { throw "ObservationPath is required for fast-edge-basis-v2-paper-observe" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-basis-v2-paper-observe" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "observe",
                "--plan", $PlanPath,
                "--probe-report", $SprintReportPath,
                "--ledger", $LedgerPath,
                "--state", $StatePath,
                "--observation", $ObservationPath
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_paper_oms.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-status" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-paper-status" }
            if (-not $LedgerPath) { throw "LedgerPath is required for fast-edge-basis-v2-paper-status" }
            if (-not $StatePath) { throw "StatePath is required for fast-edge-basis-v2-paper-status" }
            if ($MaxRuntimeSec -gt 300) { throw "MaxRuntimeSec must be <= 300 for fast-edge-basis-v2-paper-status" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @("status", "--plan", $PlanPath, "--ledger", $LedgerPath, "--state", $StatePath)
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "historical_basis_v2_paper_oms.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-observer-fixture-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required as the paper plan for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $SprintReportPath) { throw "SprintReportPath is required for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $InputPath) { throw "InputPath is required as fixture JSONL for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $OutputPath) { throw "OutputPath is required as observer PlanOnly for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $StatePath) { throw "StatePath is required as observer audit JSONL for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $LedgerPath) { throw "LedgerPath is required as accepted observation JSONL for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if (-not $RunId) { throw "RunId is required for fast-edge-basis-v2-paper-observer-fixture-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-paper-observer-fixture-plan" }
            $runtimeContract = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\paper-observer-runtime-contract-v1.json"
            $healthContract = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\paper-venue-health-gate-contract-v1.json"
            if (-not (Test-Path -LiteralPath $runtimeContract)) { throw "Frozen paper observer runtime contract is missing: $runtimeContract" }
            if (-not (Test-Path -LiteralPath $healthContract)) { throw "Frozen paper venue health contract is missing: $healthContract" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "plan",
                "--paper-plan", $PlanPath,
                "--probe-report", $SprintReportPath,
                "--runtime-contract", $runtimeContract,
                "--health-contract", $healthContract,
                "--fixture", $InputPath,
                "--output", $OutputPath,
                "--audit", $StatePath,
                "--accepted", $LedgerPath,
                "--manifest", $ManifestPath,
                "--run-id", $RunId,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "paper_observer_runtime.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-observer-fixture-run" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-paper-observer-fixture-run" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-paper-observer-fixture-run" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-paper-observer-fixture-run" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "run",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "paper_observer_runtime.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-basis-v2-paper-observer-fixture-sink" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-basis-v2-paper-observer-fixture-sink" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-basis-v2-paper-observer-fixture-sink" }
            if (-not $LedgerPath) { throw "LedgerPath is required as paper OMS ledger for fast-edge-basis-v2-paper-observer-fixture-sink" }
            if (-not $StatePath) { throw "StatePath is required as paper OMS state for fast-edge-basis-v2-paper-observer-fixture-sink" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-basis-v2-paper-observer-fixture-sink" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-paper-observer-fixture-sink" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "sink",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--ledger", $LedgerPath,
                "--state", $StatePath,
                "--manifest", $ManifestPath
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "paper_observer_runtime.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-funding-persistence-v2-plan" {
            Assert-BasisActionGate -OfflineWork
            if (-not $QualityReportPath) { throw "QualityReportPath is required for fast-edge-funding-persistence-v2-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-funding-persistence-v2-plan" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-funding-persistence-v2-plan" }
            $bankPath = if ($HypothesisBankPath) {
                $HypothesisBankPath
            } else {
                Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
            }
            $frozenGoalPath = if ($GoalPath) {
                $GoalPath
            } else {
                Join-Path $ProjectRoot "docs\plans\2026-07-16-trading-mvp-one-week-historical-edge-sprint-v2.md"
            }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "plan",
                "--quality-report", $QualityReportPath,
                "--hypothesis-bank", $bankPath,
                "--goal", $frozenGoalPath,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "funding_regime_persistence_v2.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-funding-persistence-v2-validate" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-funding-persistence-v2-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-funding-persistence-v2-validate" }
            if ($MaxRuntimeSec -gt 600) { throw "MaxRuntimeSec must be <= 600 for fast-edge-funding-persistence-v2-validate" }
            $argsList = @(
                "validate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--verify-files"
            )
            Invoke-TradingMvpCli -ScriptPath $fundingRegimePersistenceV2Cli -ArgsList $argsList
            break
        }
        "fast-edge-funding-persistence-v2-train-feasibility" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-funding-persistence-v2-train-feasibility" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-funding-persistence-v2-train-feasibility" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-funding-persistence-v2-train-feasibility" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-funding-persistence-v2-train-feasibility" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "funding_regime_persistence_v2_evaluator.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-funding-persistence-v2-oos" {
            Assert-BasisActionGate -OfflineWork
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-funding-persistence-v2-oos" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-funding-persistence-v2-oos" }
            if (-not $FeasibilityPath) { throw "FeasibilityPath is required for fast-edge-funding-persistence-v2-oos" }
            if (-not $ExpectedFeasibilityResultHash) { throw "ExpectedFeasibilityResultHash is required for fast-edge-funding-persistence-v2-oos" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-funding-persistence-v2-oos" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-funding-persistence-v2-oos" }
            $codeSnapshot = New-BasisCodeSnapshot
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--feasibility", $FeasibilityPath,
                "--expected-feasibility-result-hash", $ExpectedFeasibilityResultHash,
                "--output", $OutputPath,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            $snapshotScript = Join-Path $codeSnapshot.snapshot_path "funding_regime_persistence_v2_oos.py"
            Invoke-TradingMvpCli -ScriptPath $snapshotScript -ArgsList $argsList
            break
        }
        "fast-edge-plan" {
            Assert-FastEdgeGateOpen
            if (-not $Dataset) { throw "Dataset is required for fast-edge-plan" }
            $argsList = @(
                "fast-edge-plan",
                "--dataset", $Dataset,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--shortlist-limit", $ShortlistLimit,
                "--notional-per-leg", $FastEdgeNotionalPerLeg
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $fastEdgeCli -ArgsList $argsList
            break
        }
        "fast-edge-evaluate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-evaluate" }
            $argsList = @("fast-edge-evaluate", "--plan", $PlanPath)
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $fastEdgeCli -ArgsList $argsList
            break
        }
        "fast-edge-v2-validate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v2-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v2-validate" }
            $argsList = @(
                "validate-seal",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $residualDispersionCli -ArgsList $argsList
            break
        }
        "fast-edge-v2-evaluate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v2-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v2-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-v2-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--output", $OutputPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $residualDispersionCli -ArgsList $argsList
            break
        }
        "fast-edge-v3-validate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v3-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v3-validate" }
            $argsList = @(
                "validate-seal",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $lotteryMaxCli -ArgsList $argsList
            break
        }
        "fast-edge-v3-evaluate" {
            Assert-FastEdgeV3EvaluationAuthorized
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v3-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v3-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-v3-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--output", $OutputPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $lotteryMaxCli -ArgsList $argsList
            break
        }
        "fast-edge-v4-validate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v4-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v4-validate" }
            $argsList = @(
                "validate-seal",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $fundingPressureCli -ArgsList $argsList
            break
        }
        "fast-edge-v4-evaluate" {
            Assert-FastEdgeV4EvaluationAuthorized
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v4-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v4-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-v4-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--output", $OutputPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $fundingPressureCli -ArgsList $argsList
            break
        }
        "fast-edge-v5-validate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v5-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v5-validate" }
            $argsList = @(
                "validate-seal",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $wickRejectionCli -ArgsList $argsList
            break
        }
        "fast-edge-v5-evaluate" {
            Assert-FastEdgeV5EvaluationAuthorized
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v5-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v5-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-v5-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--output", $OutputPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $wickRejectionCli -ArgsList $argsList
            break
        }
        "fast-edge-v6-validate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v6-validate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v6-validate" }
            $argsList = @(
                "validate-seal",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $weekendLiquidityCli -ArgsList $argsList
            break
        }
        "fast-edge-v6-evaluate" {
            Assert-FastEdgeV6EvaluationAuthorized
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-v6-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-v6-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-v6-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--output", $OutputPath,
                "--expected-plan-hash", $ExpectedPlanHash
            )
            Invoke-TradingMvpCli -ScriptPath $weekendLiquidityCli -ArgsList $argsList
            break
        }
        "fast-edge-data-track-plan" {
            Assert-FastEdgeGateOpen
            if (-not $Hypothesis) { throw "Hypothesis is required for fast-edge-data-track-plan" }
            if (-not $DataType) { throw "DataType is required for fast-edge-data-track-plan" }
            if (-not $Dataset) { throw "Dataset is required for fast-edge-data-track-plan" }
            if (-not $InputMerkleSha256) { throw "InputMerkleSha256 is required for fast-edge-data-track-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-data-track-plan" }
            if ($MaxRuntimeSec -gt 1200) { throw "MaxRuntimeSec must be <= 1200 for fast-edge-data-track-plan" }
            if ($TrainCandidateEvents -le 0) { throw "TrainCandidateEvents must be > 0 for fast-edge-data-track-plan" }
            if ($TrainValidEvents -lt 0 -or $TrainValidEvents -gt $TrainCandidateEvents) {
                throw "TrainValidEvents must be in [0, TrainCandidateEvents] for fast-edge-data-track-plan"
            }
            if ($OosCandidateEvents -le 0) { throw "OosCandidateEvents must be > 0 for fast-edge-data-track-plan" }
            if ($UniqueOosDates -le 0) { throw "UniqueOosDates must be > 0 for fast-edge-data-track-plan" }

            $bankPath = if ($HypothesisBankPath) {
                $HypothesisBankPath
            } else {
                Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
            }
            $goalPath = Join-Path $ProjectRoot "docs\plans\2026-07-14-trading-mvp-canonical-goal-v3.md"
            $argsList = @(
                "build",
                "--hypothesis-bank", $bankPath,
                "--hypothesis-id", $Hypothesis,
                "--data-type", $DataType,
                "--dataset-id", $Dataset,
                "--input-merkle-sha256", $InputMerkleSha256,
                "--output", $OutputPath,
                "--goal", $goalPath,
                "--train-candidate-events", $TrainCandidateEvents,
                "--train-valid-events", $TrainValidEvents,
                "--oos-candidate-events", $OosCandidateEvents,
                "--unique-oos-dates", $UniqueOosDates,
                "--dual-venue-coverage", $DualVenueCoverage,
                "--capacity-proxy-quote-per-selected-leg", $CapacityProxyQuotePerSelectedLeg,
                "--max-runtime-sec", $MaxRuntimeSec
            )
            if ($PerVenueOosCandidateEventsJson) {
                $argsList += @("--per-venue-oos-candidate-events-json", $PerVenueOosCandidateEventsJson)
            }
            if ($TrackId) { $argsList += @("--track-id", $TrackId) }
            if ($InputPath) { $argsList += @("--dataset-root", $InputPath) }
            Invoke-TradingMvpCli -ScriptPath $dataTrackContractCli -ArgsList $argsList
            break
        }
        "fast-edge-night-schedule-plan" {
            Assert-FastEdgeGateOpen
            if (-not $Hypothesis) { throw "Hypothesis is required for fast-edge-night-schedule-plan" }
            if (-not $DataType) { throw "DataType is required for fast-edge-night-schedule-plan" }
            if (-not $ScheduleStartDate) { throw "ScheduleStartDate is required for fast-edge-night-schedule-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-night-schedule-plan" }
            if ($MaxRuntimeSec -gt 1200) { throw "MaxRuntimeSec must be <= 1200 for fast-edge-night-schedule-plan" }

            $bankPath = if ($HypothesisBankPath) {
                $HypothesisBankPath
            } else {
                Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
            }
            $goalPath = Join-Path $ProjectRoot "docs\plans\2026-07-14-trading-mvp-canonical-goal-v3.md"
            $argsList = @(
                "build",
                "--hypothesis-bank", $bankPath,
                "--hypothesis-id", $Hypothesis,
                "--data-type", $DataType,
                "--goal", $goalPath,
                "--output", $OutputPath,
                "--schedule-start-date", $ScheduleStartDate,
                "--nights", $ScheduleNights,
                "--segment-start-local", $ScheduleStartLocal,
                "--segment-duration-sec", $ScheduleSegmentDurationSec,
                "--interval-sec", $ScheduleIntervalSec,
                "--output-root", $ScheduleOutputRoot,
                "--collection-stage", $ScheduleCollectionStage
            )
            if ($QualityLedgerPath) { $argsList += @("--quality-ledger", $QualityLedgerPath) }
            if ($ScheduleCollectionStage -eq "oos_accrual") {
                if (-not $TrainPlanPath -or -not $FeasibilityPath) {
                    throw "TrainPlanPath and FeasibilityPath are required for oos_accrual schedule planning"
                }
                $argsList += @("--train-plan", $TrainPlanPath, "--feasibility", $FeasibilityPath)
            } elseif ($TrainPlanPath -or $FeasibilityPath) {
                throw "TrainPlanPath and FeasibilityPath are not allowed for train_accrual schedule planning"
            }
            Invoke-TradingMvpCli -ScriptPath $nightSchedulePlanCli -ArgsList $argsList
            break
        }
        "fast-edge-night-schedule-status" {
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-night-schedule-status" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-night-schedule-status" }
            if ($MaxRuntimeSec -gt 120) { throw "MaxRuntimeSec must be <= 120 for fast-edge-night-schedule-status" }
            $resolvedApprovalRoot = if ($ApprovalRecordRoot) {
                $ApprovalRecordRoot
            } else {
                Join-Path $ProjectRoot "docs\agent-log\night-schedule-approvals"
            }
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval-record-root", $resolvedApprovalRoot
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $nightScheduleStatusCli -ArgsList $argsList
            break
        }
        "fast-edge-night-schedule-quality" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-night-schedule-quality" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-night-schedule-quality" }
            if (-not $QualityLedgerPath) { throw "QualityLedgerPath is required for fast-edge-night-schedule-quality" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-night-schedule-quality" }
            $resolvedApprovalRoot = if ($ApprovalRecordRoot) {
                $ApprovalRecordRoot
            } else {
                Join-Path $ProjectRoot "docs\agent-log\night-schedule-approvals"
            }
            $argsList = @(
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--approval-record-root", $resolvedApprovalRoot,
                "--ledger", $QualityLedgerPath
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $nightScheduleQualityCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-futility-plan" {
            Assert-FastEdgeGateOpen
            if (-not $QualityLedgerPath) { throw "QualityLedgerPath is required for fast-edge-pit-futility-plan" }
            if (-not $Hypothesis) { throw "Hypothesis is required for fast-edge-pit-futility-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-futility-plan" }
            if ($MaxRuntimeSec -gt 1200) { throw "MaxRuntimeSec must be <= 1200 for fast-edge-pit-futility-plan" }
            $bankPath = if ($HypothesisBankPath) {
                $HypothesisBankPath
            } else {
                Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
            }
            $argsList = @(
                "plan",
                "--quality-ledger", $QualityLedgerPath,
                "--hypothesis-bank", $bankPath,
                "--hypothesis-id", $Hypothesis,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftFutilityCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-futility-evaluate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-pit-futility-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-pit-futility-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-futility-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-futility-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftFutilityCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-input-plan" {
            Assert-FastEdgeGateOpen
            if (-not $QualityLedgerPath) { throw "QualityLedgerPath is required for fast-edge-pit-input-plan" }
            if (-not $Hypothesis) { throw "Hypothesis is required for fast-edge-pit-input-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-input-plan" }
            if ($MaxRuntimeSec -gt 1200) { throw "MaxRuntimeSec must be <= 1200 for fast-edge-pit-input-plan" }
            $bankPath = if ($HypothesisBankPath) {
                $HypothesisBankPath
            } else {
                Join-Path $ProjectRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
            }
            $argsList = @(
                "plan",
                "--quality-ledger", $QualityLedgerPath,
                "--hypothesis-bank", $bankPath,
                "--hypothesis-id", $Hypothesis,
                "--plan-stage", $PitPlanStage,
                "--output", $OutputPath
            )
            if ($PitPlanStage -eq "full_evaluation") {
                if (-not $TrainPlanPath) { throw "TrainPlanPath is required for full_evaluation" }
                if (-not $FeasibilityPath) { throw "FeasibilityPath is required for full_evaluation" }
                $argsList += @("--train-plan", $TrainPlanPath, "--feasibility", $FeasibilityPath)
            } elseif ($TrainPlanPath -or $FeasibilityPath) {
                throw "TrainPlanPath and FeasibilityPath are not allowed for train_feasibility"
            }
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-feasibility" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-pit-feasibility" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-pit-feasibility" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-feasibility" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-feasibility" }
            $argsList = @(
                "feasibility",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-evaluate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-pit-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-pit-evaluate" }
            if (-not $FeasibilityPath) { throw "FeasibilityPath is required for fast-edge-pit-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--feasibility", $FeasibilityPath,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-execution-probe-plan" {
            Assert-FastEdgeGateOpen
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-pit-execution-probe-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-execution-probe-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-execution-probe-plan" }
            $argsList = @(
                "plan",
                "--evaluation", $EvaluationPath,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftProbeCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-execution-probe-evaluate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-pit-execution-probe-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-pit-execution-probe-evaluate" }
            if (-not $ManifestPath) { throw "ManifestPath is required for fast-edge-pit-execution-probe-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-execution-probe-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-execution-probe-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--manifest", $ManifestPath,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftProbeCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-paper-plan" {
            Assert-FastEdgeGateOpen
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-pit-paper-plan" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-paper-plan" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-paper-plan" }
            $argsList = @(
                "plan",
                "--execution-evaluation", $EvaluationPath,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftPaperCli -ArgsList $argsList
            break
        }
        "fast-edge-pit-paper-evaluate" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-pit-paper-evaluate" }
            if (-not $ExpectedPlanHash) { throw "ExpectedPlanHash is required for fast-edge-pit-paper-evaluate" }
            if (-not $PaperApprovalPath) { throw "PaperApprovalPath is required for fast-edge-pit-paper-evaluate" }
            if (-not $OutputPath) { throw "OutputPath is required for fast-edge-pit-paper-evaluate" }
            if ($MaxRuntimeSec -gt 1800) { throw "MaxRuntimeSec must be <= 1800 for fast-edge-pit-paper-evaluate" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath,
                "--approval", $PaperApprovalPath,
                "--expected-plan-hash", $ExpectedPlanHash,
                "--output", $OutputPath
            )
            Invoke-TradingMvpCli -ScriptPath $pitMembershipDriftPaperCli -ArgsList $argsList
            break
        }
        "fast-edge-feasibility" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-feasibility" }
            $argsList = @(
                "evaluate",
                "--plan", $PlanPath
            )
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $feasibilityGateCli -ArgsList $argsList
            break
        }
        "fast-edge-execution-probe" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-execution-probe" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-execution-probe" }
            $probeDuration = if ($DurationSec -gt 0) { $DurationSec } else { 1200 }
            if ($probeDuration -gt $MaxRuntimeSec) {
                throw "DurationSec=$probeDuration must be <= MaxRuntimeSec=$MaxRuntimeSec"
            }
            $argsList = @(
                "fast-edge-execution-probe",
                "--plan", $PlanPath,
                "--evaluation", $EvaluationPath,
                "--duration-sec", $probeDuration,
                "--interval-sec", $IntervalSec,
                "--max-runtime-sec", $MaxRuntimeSec,
                "--top-n", $TopN
            )
            if ($ExecutionProbePath) { $argsList += @("--output", $ExecutionProbePath) }
            elseif ($OutputPath) { $argsList += @("--output", $OutputPath) }
            if ($Resume) { $argsList += "--resume" }
            Invoke-TradingMvpCli -ScriptPath $fastEdgeCli -ArgsList $argsList
            break
        }
        "fast-edge-report" {
            Assert-FastEdgeGateOpen
            if (-not $PlanPath) { throw "PlanPath is required for fast-edge-report" }
            if (-not $EvaluationPath) { throw "EvaluationPath is required for fast-edge-report" }
            $argsList = @(
                "fast-edge-report",
                "--plan", $PlanPath,
                "--evaluation", $EvaluationPath
            )
            if ($ExecutionProbePath) { $argsList += @("--execution-probe", $ExecutionProbePath) }
            if ($OutputPath) { $argsList += @("--output", $OutputPath) }
            Invoke-TradingMvpCli -ScriptPath $fastEdgeCli -ArgsList $argsList
            break
        }
        "paper-forward-segment" {
            Assert-FastEdgeGateOpen
            if (-not $FastEdgeReportPath) { throw "FastEdgeReportPath is required for paper-forward-segment" }
            if (-not $ObservationPath) { throw "ObservationPath is required for paper-forward-segment" }
            if (-not $StatePath) { throw "StatePath is required for paper-forward-segment" }
            $argsList = @(
                "paper-forward-segment",
                "--report", $FastEdgeReportPath,
                "--observation", $ObservationPath,
                "--state", $StatePath
            )
            Invoke-TradingMvpCli -ScriptPath $fastEdgeCli -ArgsList $argsList
            break
        }
        "setup-registry" {
            $argsList = @("--config", $Config, "setup-registry")
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "experiment-record" {
            if (-not $SourceVideoId) { throw "SourceVideoId is required for experiment-record" }
            if (-not $SourceUrl) { throw "SourceUrl is required for experiment-record" }
            if (-not $ClaimFamily) { throw "ClaimFamily is required for experiment-record" }
            if (-not $Hypothesis) { throw "Hypothesis is required for experiment-record" }
            if (-not $SetupId) { throw "SetupId is required for experiment-record" }
            if (-not $Dataset) { throw "Dataset is required for experiment-record" }
            $argsList = @(
                "--config", $Config,
                "experiment-record",
                "--source-video-id", $SourceVideoId,
                "--source-url", $SourceUrl,
                "--source-channel", $SourceChannel,
                "--participant", $Participant,
                "--claim-family", $ClaimFamily,
                "--hypothesis", $Hypothesis,
                "--setup-id", $SetupId,
                "--dataset", $Dataset,
                "--verdict", $Verdict,
                "--verdict-reason", $VerdictReason,
                "--notes", $Notes,
                "--fee-schedule-revision", $FeeScheduleRevision,
                "--evaluation-scope", $EvaluationScope,
                "--oos-status", $OosStatus
            )
            if ($ConfigJson) {
                $argsList += @("--config-json", $ConfigJson)
            }
            if ($ResultPath) {
                $argsList += @("--result-path", $ResultPath)
            }
            if ($MetricsJson) {
                $argsList += @("--metrics-json", $MetricsJson)
            }
            if ($Tags) {
                $argsList += @("--tags", $Tags)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
        "experiment-list" {
            $argsList = @("--config", $Config, "experiment-list")
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($Verdict -ne "untested") {
                $argsList += @("--verdict", $Verdict)
            }
            if ($SetupId) {
                $argsList += @("--setup-id", $SetupId)
            }
            $argsList += @("--top-n", $TopN)
            Invoke-TradingMvpCli -ArgsList $argsList
            break
        }
    }
}
finally {
    Pop-Location
}
