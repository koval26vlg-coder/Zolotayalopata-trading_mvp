param(
    [string]$Config = "",
    [ValidateSet("universe","collect","backtest","run","multi-run","ws-collect","ws-normalize","perp-collect","perp-report","event-quality-report","event-slice-optimizer","perp-postprocess","ws-replay","ws-grid-search","perp-replay","perp-grid-search","funding-scan","funding-coverage","funding-collect","funding-status","funding-collect-diagnostics","funding-wait-ready","funding-rank","funding-gate-report","funding-regime-report","funding-frontier-report","funding-decision-report","funding-progress-report","funding-backtest","funding-sensitivity","funding-oos-backtest","funding-walk-forward","funding-postprocess","funding-finalize","funding-final-review","funding-paper-plan","funding-paper-forward","funding-paper-decision-report","funding-goal-audit","fast-edge-basis-v2-paper-observer-fixture-plan","fast-edge-basis-v2-paper-observer-fixture-run","fast-edge-basis-v2-paper-observer-fixture-sink","setup-registry","experiment-record","experiment-list")]
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
    [string]$PaperObserverPaperPlanPath = "",
    [string]$PaperObserverProbeReportPath = "",
    [string]$PaperObserverRuntimeContractPath = "",
    [string]$PaperObserverHealthContractPath = "",
    [string]$PaperObserverFixturePath = "",
    [string]$PaperObserverPlanPath = "",
    [string]$PaperObserverExpectedPlanHash = "",
    [string]$PaperObserverAuditPath = "",
    [string]$PaperObserverAcceptedPath = "",
    [string]$PaperObserverManifestPath = "",
    [string]$PaperObserverRunId = "",
    [string]$PaperObserverLedgerPath = "",
    [string]$PaperObserverStatePath = "",
    [ValidateRange(1, 1800)]
    [int]$PaperObserverMaxRuntimeSec = 600,
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
    [string]$SourceVideoId = "",
    [string]$SourceUrl = "",
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
    [string]$Notes = ""
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
$paperObserverRuntime = Join-Path $PSScriptRoot "src\paper_observer_runtime.py"

Push-Location $ProjectRoot
try {
    switch ($Action) {
        "collect" {
            & $python $cli --config $Config collect --seconds $Seconds
            break
        }
        "backtest" {
            & $python $cli --config $Config backtest
            break
        }
        "run" {
            & $python $cli --config $Config run --mode $Mode --cycles $Cycles
            break
        }
        "universe" {
            & $python $cli --config $Config universe
            break
        }
        "fast-edge-basis-v2-paper-observer-fixture-plan" {
            $required = @(
                @{ Name = "PaperObserverPaperPlanPath"; Value = $PaperObserverPaperPlanPath },
                @{ Name = "PaperObserverProbeReportPath"; Value = $PaperObserverProbeReportPath },
                @{ Name = "PaperObserverRuntimeContractPath"; Value = $PaperObserverRuntimeContractPath },
                @{ Name = "PaperObserverHealthContractPath"; Value = $PaperObserverHealthContractPath },
                @{ Name = "PaperObserverFixturePath"; Value = $PaperObserverFixturePath },
                @{ Name = "PaperObserverPlanPath"; Value = $PaperObserverPlanPath },
                @{ Name = "PaperObserverAuditPath"; Value = $PaperObserverAuditPath },
                @{ Name = "PaperObserverAcceptedPath"; Value = $PaperObserverAcceptedPath },
                @{ Name = "PaperObserverManifestPath"; Value = $PaperObserverManifestPath },
                @{ Name = "PaperObserverRunId"; Value = $PaperObserverRunId }
            )
            foreach ($item in $required) {
                if ([string]::IsNullOrWhiteSpace([string]$item.Value)) {
                    throw "$($item.Name) is required for $Action"
                }
            }
            $argsList = @(
                "plan",
                "--paper-plan", $PaperObserverPaperPlanPath,
                "--probe-report", $PaperObserverProbeReportPath,
                "--runtime-contract", $PaperObserverRuntimeContractPath,
                "--health-contract", $PaperObserverHealthContractPath,
                "--fixture", $PaperObserverFixturePath,
                "--output", $PaperObserverPlanPath,
                "--audit", $PaperObserverAuditPath,
                "--accepted", $PaperObserverAcceptedPath,
                "--manifest", $PaperObserverManifestPath,
                "--run-id", $PaperObserverRunId,
                "--max-runtime-sec", $PaperObserverMaxRuntimeSec
            )
            & $python $paperObserverRuntime @argsList
            if ($LASTEXITCODE -ne 0) {
                throw "paper observer fixture plan failed with exit code $LASTEXITCODE"
            }
            break
        }
        "fast-edge-basis-v2-paper-observer-fixture-run" {
            if ([string]::IsNullOrWhiteSpace($PaperObserverPlanPath)) {
                throw "PaperObserverPlanPath is required for $Action"
            }
            if ([string]::IsNullOrWhiteSpace($PaperObserverExpectedPlanHash)) {
                throw "PaperObserverExpectedPlanHash is required for $Action"
            }
            & $python $paperObserverRuntime run `
                --plan $PaperObserverPlanPath `
                --expected-plan-hash $PaperObserverExpectedPlanHash
            if ($LASTEXITCODE -ne 0) {
                throw "paper observer fixture run failed with exit code $LASTEXITCODE"
            }
            break
        }
        "fast-edge-basis-v2-paper-observer-fixture-sink" {
            $required = @(
                @{ Name = "PaperObserverPlanPath"; Value = $PaperObserverPlanPath },
                @{ Name = "PaperObserverExpectedPlanHash"; Value = $PaperObserverExpectedPlanHash },
                @{ Name = "PaperObserverLedgerPath"; Value = $PaperObserverLedgerPath },
                @{ Name = "PaperObserverStatePath"; Value = $PaperObserverStatePath },
                @{ Name = "PaperObserverManifestPath"; Value = $PaperObserverManifestPath }
            )
            foreach ($item in $required) {
                if ([string]::IsNullOrWhiteSpace([string]$item.Value)) {
                    throw "$($item.Name) is required for $Action"
                }
            }
            $argsList = @(
                "sink",
                "--plan", $PaperObserverPlanPath,
                "--expected-plan-hash", $PaperObserverExpectedPlanHash,
                "--ledger", $PaperObserverLedgerPath,
                "--state", $PaperObserverStatePath,
                "--manifest", $PaperObserverManifestPath
            )
            & $python $paperObserverRuntime @argsList
            if ($LASTEXITCODE -ne 0) {
                throw "paper observer fixture sink failed with exit code $LASTEXITCODE"
            }
            break
        }
        "multi-run" {
            $argsList = @("--config", $Config, "multi-run", "--exchanges", $Exchanges, "--max-pairs-per-exchange", $MaxPairsPerExchange, "--max-symbols", $MaxSymbols, "--paper-notional-quote", $PaperNotionalQuote)
            if ($DurationSec -gt 0) {
                $argsList += @("--duration-sec", $DurationSec)
            } else {
                $argsList += @("--cycles", $Cycles)
            }
            & $python $cli @argsList
            break
        }
        "ws-collect" {
            $duration = $DurationSec
            if ($duration -le 0) {
                $duration = $Seconds
            }
            $argsList = @("--config", $Config, "ws-collect", "--exchanges", $Exchanges, "--max-pairs-per-exchange", $MaxPairsPerExchange, "--max-symbols", $MaxSymbols, "--duration-sec", $duration, "--update-interval", $UpdateInterval)
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($AllowShort) {
                $argsList += @("--allow-short")
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            & $python $cli @argsList
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
                "--top-n", $TopN
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
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
            & $python $cli @argsList
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
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            & $python $cli @argsList
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
                "--top-n", $TopN
            )
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            if ($QualityFilter) {
                $argsList += @("--quality-filter")
            }
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            if ($InputPath) {
                $argsList += @("--input", $InputPath)
            }
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
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
            & $python $cli @argsList
            break
        }
        "setup-registry" {
            $argsList = @("--config", $Config, "setup-registry")
            if ($OutputPath) {
                $argsList += @("--output", $OutputPath)
            }
            & $python $cli @argsList
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
                "--participant", $Participant,
                "--claim-family", $ClaimFamily,
                "--hypothesis", $Hypothesis,
                "--setup-id", $SetupId,
                "--dataset", $Dataset,
                "--verdict", $Verdict,
                "--verdict-reason", $VerdictReason,
                "--notes", $Notes
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
            & $python $cli @argsList
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
            & $python $cli @argsList
            break
        }
    }
}
finally {
    Pop-Location
}
