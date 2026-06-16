# 2026-06-15 Funding OOS Gate

## Purpose

Add an out-of-sample gate for funding/basis carry research so a strategy cannot be accepted only by in-sample performance.

This remains research-only: no API keys, no live orders, no leverage, no trading recommendations.

## Implemented

- Added `FundingOosConfig`.
- Added `run_funding_oos_backtest()`.
- Added `run_funding_oos_backtest_file()`.
- Added default artifact path `funding_oos_backtest_*.json`.
- Added CLI command `funding-oos-backtest`.
- Added PowerShell action `-Action funding-oos-backtest`.

## OOS Gate Behavior

Rows are sorted by timestamp and split into:

- in-sample train segment;
- out-of-sample segment.

The gate runs the same funding backtest config on both segments and evaluates acceptance/stress independently. Overall `accepted=true` only when both in-sample and out-of-sample acceptance pass.

## Verification

- Added regression: `test_oos_backtest_requires_in_sample_and_out_of_sample_acceptance`.
- Added regression: `test_oos_backtest_rejects_insufficient_oos_rows`.
- Added CLI parser coverage for `funding-oos-backtest`.
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 27 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 99 tests ... OK`

## CLI Smoke

Smoke command used a temporary 4-row JSONL fixture through `trading_mvp/run_mvp.ps1 -Action funding-oos-backtest`.

Result:

- `ok=true`
- `status=completed`
- `accepted=true` under deliberately loose smoke thresholds
- split:
  - `total_rows=4`
  - `train_rows=2`
  - `oos_rows=2`

The smoke was only a plumbing check, not a strategy result.

## Live Funding Collect Status

Latest status:

- `status=running_or_waiting`
- `ready_for_postprocess=false`
- `final=false`
- `completed_cycles=12 / 288`
- `rows=264`
- `line_count=264`
- `line_count_matches_manifest=true`
- `errors=68`
- `last_write_age_sec≈136`
- `stderr=0 bytes`

## Next Gate

When the 24h collect becomes final:

1. Run guarded `funding-postprocess`.
2. Run `funding-oos-backtest` on the final JSONL with the same persistence/regime/stress/acceptance thresholds.
3. Accept the research phase only if both the full guarded postprocess and OOS gate pass.
