# Funding Stress Gates

Date: 2026-06-15

## Goal

Advance the research-only funding/basis carry pipeline beyond base-case acceptance gates. A strategy should not pass only because the historical base path looks acceptable; it must also survive conservative stress assumptions for basis widening, spread widening and funding flip.

## Current 24h Collect Status

The active 24h collect is still running and remains partial.

```json
{
  "pid": 4356,
  "process_alive": true,
  "manifest_final": false,
  "completed_cycles": 4,
  "cycles": 288,
  "rows": 96,
  "errors": 24,
  "stderr_bytes": 0
}
```

Postprocess remains blocked until `manifest.final=true`.

## Implementation

- Added `FundingStressConfig`.
- Added `stress_funding_backtest_metrics`.
- Added `total_notional_quote` and `avg_notional_quote` to funding backtest metrics.
- Extended `evaluate_funding_backtest_metrics` to include optional stress evaluation.
- Added stress output to the `acceptance` block.
- Added CLI flags:
  - `--stress-enabled`
  - `--stress-adverse-basis-bps`
  - `--stress-spread-widen-bps`
  - `--stress-funding-flip-bps`
  - `--stress-min-net-pnl-quote`
  - `--stress-max-drawdown-quote`
- Added PowerShell wrapper parameters:
  - `-FundingStress`
  - `-FundingStressAdverseBasisBps`
  - `-FundingStressSpreadWidenBps`
  - `-FundingStressFundingFlipBps`
  - `-FundingStressMinNetPnlQuote`
  - `-FundingStressMaxDrawdownQuote`

## Stress Formula

```text
stress_cost_bps = adverse_basis_bps + 2 * spread_widen_bps + funding_flip_bps
stress_cost_quote = total_notional_quote * stress_cost_bps / 10000
stress_net_pnl_quote = net_pnl_quote - stress_cost_quote
stress_max_drawdown_quote = max_drawdown_quote + stress_cost_quote
```

The model is deliberately conservative and simple for v1. It is not a live execution model.

## Verification

Red test observed:

```text
ImportError: cannot import name 'FundingStressConfig'
```

Targeted funding/basis suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Result:

```text
Ran 17 tests in 0.033s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result:

```text
Ran 89 tests in 0.120s
OK
```

Partial guard smoke with stress enabled:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" -ReportOutputPath "exports\trading-mvp\funding\funding_rank_partial_stress_guard_should_not_exist.json" -GridOutputPath "exports\trading-mvp\backtests\funding_backtest_partial_stress_guard_should_not_exist.json" -TopN 20 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0 -FundingAcceptMinTrades 20 -FundingAcceptMinWinRate 0.6 -FundingAcceptMinExpectancyQuote 0 -FundingAcceptMinNetPnlQuote 0 -FundingAcceptMaxDrawdownQuote 5 -FundingAcceptMinProfitFactor 1.2 -FundingStress -FundingStressAdverseBasisBps 10 -FundingStressSpreadWidenBps 5 -FundingStressFundingFlipBps 2 -FundingStressMinNetPnlQuote 0 -FundingStressMaxDrawdownQuote 5
```

Result:

```json
{
  "ok": false,
  "status": "not_final",
  "manifest_summary": {
    "final": false,
    "completed_cycles": 4,
    "cycles": 288,
    "rows": 96,
    "errors": 24
  }
}
```

Output files:

```json
{
  "RankExists": false,
  "BacktestExists": false
}
```

## Next Step

After `manifest.final=true`, run:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" -TopN 30 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0 -NotionalQuote 100 -FundingMinRate 0 -FundingMinTotalScore 0 -FundingMaxSpotSpreadBps 30 -FundingMaxPerpSpreadBps 30 -FundingMaxAbsBasisBps 500 -FundingAcceptMinTrades 20 -FundingAcceptMinWinRate 0.6 -FundingAcceptMinExpectancyQuote 0 -FundingAcceptMinNetPnlQuote 0 -FundingAcceptMaxDrawdownQuote 5 -FundingAcceptMinProfitFactor 1.2 -FundingStress -FundingStressAdverseBasisBps 10 -FundingStressSpreadWidenBps 5 -FundingStressFundingFlipBps 2 -FundingStressMinNetPnlQuote 0 -FundingStressMaxDrawdownQuote 5
```

Do not proceed to live orders unless base acceptance, stress acceptance, and later out-of-sample/paper-forward checks pass.
