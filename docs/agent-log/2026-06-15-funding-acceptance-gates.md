# Funding Acceptance Gates

Date: 2026-06-15

## Goal

Move the research-only objective closer to a measurable decision process. Funding/basis postprocess should not only produce rank and backtest artifacts; it must also classify the result against explicit acceptance gates:

- net PnL after fees/slippage
- winrate
- expectancy
- max drawdown
- sample size
- profit factor

## Current 24h Collect Status

The active collect is still running and remains partial.

```json
{
  "pid": 4356,
  "process_alive": true,
  "manifest_final": false,
  "completed_cycles": 3,
  "cycles": 288,
  "rows": 72,
  "errors": 18,
  "stderr_bytes": 0
}
```

Guarded postprocess was tested against this partial dataset and correctly refused to run:

```json
{
  "ok": false,
  "status": "not_final",
  "rank_exists": false,
  "backtest_exists": false
}
```

## Implementation

- Added `FundingAcceptanceConfig`.
- Added `evaluate_funding_backtest_metrics`.
- Added `acceptance` block to `run_funding_postprocess_file` output.
- Added CLI flags:
  - `--accept-min-trades`
  - `--accept-min-win-rate`
  - `--accept-min-expectancy-quote`
  - `--accept-min-net-pnl-quote`
  - `--accept-max-drawdown-quote`
  - `--accept-min-profit-factor`
- Added PowerShell wrapper parameters:
  - `-FundingAcceptMinTrades`
  - `-FundingAcceptMinWinRate`
  - `-FundingAcceptMinExpectancyQuote`
  - `-FundingAcceptMinNetPnlQuote`
  - `-FundingAcceptMaxDrawdownQuote`
  - `-FundingAcceptMinProfitFactor`

## Verification

Red test observed:

```text
ImportError: cannot import name 'FundingAcceptanceConfig'
```

Targeted funding/basis suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Result:

```text
Ran 15 tests in 0.027s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result:

```text
Ran 87 tests in 0.129s
OK
```

Partial guard smoke:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" -ReportOutputPath "exports\trading-mvp\funding\funding_rank_partial_acceptance_guard_should_not_exist.json" -GridOutputPath "exports\trading-mvp\backtests\funding_backtest_partial_acceptance_guard_should_not_exist.json" -TopN 20 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0 -FundingAcceptMinTrades 20 -FundingAcceptMinWinRate 0.6 -FundingAcceptMinExpectancyQuote 0 -FundingAcceptMinNetPnlQuote 0 -FundingAcceptMaxDrawdownQuote 5 -FundingAcceptMinProfitFactor 1.2
```

Result:

```json
{
  "ok": false,
  "status": "not_final",
  "manifest_summary": {
    "final": false,
    "completed_cycles": 3,
    "cycles": 288,
    "rows": 72,
    "errors": 18
  }
}
```

## Next Step

After `manifest.final=true`, run guarded postprocess with acceptance gates:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" -TopN 30 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0 -NotionalQuote 100 -FundingMinRate 0 -FundingMinTotalScore 0 -FundingMaxSpotSpreadBps 30 -FundingMaxPerpSpreadBps 30 -FundingMaxAbsBasisBps 500 -FundingAcceptMinTrades 20 -FundingAcceptMinWinRate 0.6 -FundingAcceptMinExpectancyQuote 0 -FundingAcceptMinNetPnlQuote 0 -FundingAcceptMaxDrawdownQuote 5 -FundingAcceptMinProfitFactor 1.2
```

Do not move to live orders unless acceptance passes and later out-of-sample/paper-forward checks also pass.
