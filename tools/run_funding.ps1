function Invoke-FundingPipeline {
    switch ($Action) {
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
    }
}
