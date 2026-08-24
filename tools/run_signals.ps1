function Invoke-SignalsPipeline {
    switch ($Action) {
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
    }
}
