# 2026-06-15 Funding Regime Gates

## Goal

Move `funding/basis carry` from raw opportunity scanning toward acceptance-grade research by adding rolling market-quality gates before entries and exits.

The project goal remains research-only: no API keys, no live orders, no leverage, and no investment advice. A strategy can advance only if it passes net PnL after fees/slippage, winrate, expectancy, drawdown, sample size, and out-of-sample checks.

## Implemented

- Added rolling regime fields to `FundingBacktestConfig`:
  - `min_regime_observations`
  - `min_perp_volume_24h_quote`
  - `max_basis_std_bps`
  - `max_avg_spot_spread_bps`
  - `max_avg_perp_spread_bps`
- Added rolling regime metrics from current/past rows only:
  - average/min perp 24h quote volume
  - average/std/abs-max basis
  - average spot/perp spread
- Added entry and exit gates for low-volume, unstable-basis, and wide-spread regimes.
- Exposed the new gates in CLI and `trading_mvp/run_mvp.ps1` for `funding-backtest` and `funding-postprocess`.
- Added unit coverage for low-volume and unstable-basis entry blocking.

## Verification

- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 19 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 91 tests ... OK`

## Guard Smoke

Command: `trading_mvp/run_mvp.ps1 -Action funding-postprocess` against the active 24h rolling manifest with acceptance, stress, persistence, and regime gates.

Result:

```json
{
  "ok": false,
  "status": "not_final",
  "manifest_summary": {
    "final": false,
    "completed_cycles": 5,
    "cycles": 288,
    "rows": 120,
    "errors": 30,
    "duration_sec": 1376.5576684474945
  }
}
```

No rank/backtest artifacts were created from the partial dataset.

## Active 24h Collect Status

- PID: `4356`
- Alive: `true`
- Output: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Current rows: `120`
- Completed cycles: `5 / 288`
- Errors: `30`
- Last write: `2026-06-15T16:43:43+03:00`
- Manifest final: `false`

## Next Command After final=true

Run guarded postprocess with strict persistence, regime, acceptance, and stress gates:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess `
  -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" `
  -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" `
  -ReportOutputPath "exports\trading-mvp\funding\funding_rank_24h_rolling_20260615_162045.json" `
  -GridOutputPath "exports\trading-mvp\backtests\funding_backtest_24h_rolling_20260615_162045.json" `
  -TopN 30 `
  -FundingMinObservations 6 `
  -FundingMinPositiveRatio 0.75 `
  -FundingMinPersistenceScore 0 `
  -FundingMinRegimeObservations 6 `
  -FundingMinPerpVolume24hQuote 1000000 `
  -FundingMaxBasisStdBps 10 `
  -FundingMaxAvgSpotSpreadBps 10 `
  -FundingMaxAvgPerpSpreadBps 10 `
  -FundingAcceptMinTrades 20 `
  -FundingAcceptMinWinRate 0.6 `
  -FundingAcceptMinExpectancyQuote 0 `
  -FundingAcceptMinNetPnlQuote 0 `
  -FundingAcceptMaxDrawdownQuote 5 `
  -FundingAcceptMinProfitFactor 1.2 `
  -FundingStress `
  -FundingStressAdverseBasisBps 10 `
  -FundingStressSpreadWidenBps 5 `
  -FundingStressFundingFlipBps 2 `
  -FundingStressMinNetPnlQuote 0 `
  -FundingStressMaxDrawdownQuote 5
```

## Decision Rule

- If no config passes: do not expand to live or paper execution; either collect longer data or test a new signal family.
- If configs pass in-sample: freeze config and run paper-forward out-of-sample.
- If paper-forward fails: reject or tighten filters.
- If paper-forward passes: prepare live-readiness checklist, still without enabling live orders automatically.
