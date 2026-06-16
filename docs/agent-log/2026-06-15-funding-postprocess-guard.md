# Funding Postprocess Guard

Date: 2026-06-15

## Goal

Prevent accidental funding/basis analytics on incomplete 24h collection data. The active `funding_collect_24h_rolling_20260615_162045` process is still running, so rank/backtest must be blocked until its manifest is final unless `--allow-partial` is explicitly passed.

## Current Collect Status

Metadata:

```text
docs/agent-log/2026-06-15-funding-collect-24h-rolling-20260615_162045.json
```

Runtime check:

```json
{
  "ProcessAlive": true,
  "OutLines": 24,
  "OutBytes": 23921,
  "ManifestFinal": false,
  "CompletedCycles": 1,
  "Rows": 24,
  "Errors": 6,
  "ErrBytes": 0,
  "LastWrite": "2026-06-15T16:21:21.5648719+03:00"
}
```

Postprocess was intentionally not run on this partial dataset.

## Implementation

- Added `run_funding_postprocess_file` in `trading_mvp/src/basis.py`.
- Added `default_funding_postprocess_output`.
- Added `funding-postprocess` CLI command.
- Added `funding-postprocess` PowerShell wrapper action.
- The guard returns structured statuses:
  - `manifest_required`
  - `manifest_missing`
  - `not_final`
  - `completed`
- Rank/backtest files are not created when `require_final=true` and manifest is not final.

## Verification

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Result:

```text
Ran 13 tests in 0.040s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result:

```text
Ran 85 tests in 0.144s
OK
```

Smoke guard on active partial collect:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" -ReportOutputPath "exports\trading-mvp\funding\funding_rank_partial_guard_should_not_exist.json" -GridOutputPath "exports\trading-mvp\backtests\funding_backtest_partial_guard_should_not_exist.json" -TopN 20 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0
```

Result:

```json
{
  "ok": false,
  "status": "not_final",
  "manifest_summary": {
    "final": false,
    "completed_cycles": 1,
    "cycles": 288,
    "rows": 24,
    "errors": 6
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

When the manifest becomes `final=true`, run:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" -TopN 30 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0 -NotionalQuote 100 -FundingMinRate 0 -FundingMinTotalScore 0 -FundingMaxSpotSpreadBps 30 -FundingMaxPerpSpreadBps 30 -FundingMaxAbsBasisBps 500
```

Then evaluate net PnL after fees/slippage, winrate, expectancy, drawdown proxy, sample size and basis/funding PnL split. Do not move to live orders from this step.
