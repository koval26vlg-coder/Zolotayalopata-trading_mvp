# Funding Drawdown Metrics

Date: 2026-06-15

## Goal

Advance the active research-only objective by adding a required acceptance metric to the funding/basis carry backtester: drawdown. The strategy cannot be evaluated only by net PnL and winrate; it also needs an equity curve and max drawdown after fees/slippage.

## Current 24h Collect Status

The active public-data collect is still running and must not be postprocessed yet.

```json
{
  "pid": 4356,
  "process_alive": true,
  "output": "exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl",
  "manifest": "exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json",
  "manifest_final": false,
  "completed_cycles": 2,
  "rows": 48,
  "errors": 12,
  "stderr_bytes": 0
}
```

## Implementation

- Added `equity_curve` to `run_funding_backtest` output.
- Added chronological equity points sorted by `exit_ts`.
- Added funding backtest metrics:
  - `ending_equity_quote`
  - `peak_equity_quote`
  - `max_drawdown_quote`
  - `max_drawdown_pct`

## Verification

Red test observed:

```text
AssertionError: 'max_drawdown_quote' not found
```

Targeted test after implementation:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_backtest_reports_equity_curve_and_drawdown
```

Result:

```text
Ran 1 test in 0.000s
OK
```

Funding/basis tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Result:

```text
Ran 14 tests in 0.033s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result:

```text
Ran 86 tests in 0.127s
OK
```

## 6h Smoke With Drawdown

Artifact:

```text
exports/trading-mvp/backtests/funding_backtest_6h_reliable_20260605_195336_rolling_persistence_drawdown.json
```

Metrics:

```json
{
  "rows": 23,
  "markets": 2,
  "total_trades": 2,
  "wins": 0,
  "losses": 2,
  "win_rate": 0.0,
  "funding_pnl_quote": 0.002753299162619644,
  "basis_pnl_quote": -0.12992329891051746,
  "fees_quote": 0.7,
  "slippage_quote": 0.08,
  "net_pnl_quote": -0.9071699997478977,
  "expectancy_quote": -0.45358499987394885,
  "profit_factor": 0.0,
  "ending_equity_quote": -0.9071699997478977,
  "peak_equity_quote": 0.0,
  "max_drawdown_quote": 0.9071699997478977,
  "max_drawdown_pct": null
}
```

Verdict: the 6h funding/basis sample remains negative and is not a live candidate.

## Next Step

Wait for `funding_collect_24h_rolling_20260615_162045.manifest.json` to become `final=true`, then run guarded `funding-postprocess` and evaluate the full gate set:

- net PnL after fees/slippage
- winrate
- expectancy
- max drawdown
- sample size
- funding PnL vs basis PnL split

No live orders or API keys.
