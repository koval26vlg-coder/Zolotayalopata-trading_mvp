# 2026-06-15 Funding Status Healthcheck

## Purpose

Add a lightweight health-check for long-running funding collection so the project can distinguish:

- final datasets ready for postprocess;
- active collectors sleeping between cycles;
- stale or broken collectors;
- manifest/output line-count mismatches.

This keeps the research pipeline gated: `funding-postprocess` must not run until `ready_for_postprocess=true`.

## Implemented

- Added `funding_collect_status()` in `trading_mvp/src/basis.py`.
- Added CLI command: `funding-status`.
- Added PowerShell action: `-Action funding-status`.
- Added tests for stale/line-count mismatch and CLI parser coverage.

## Verification

- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 23 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 95 tests ... OK`

## Live Status Command

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-status `
  -InputPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl" `
  -ManifestPath "exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json" `
  -FundingStatusStaleAfterSec 900
```

Live output summary:

- `status=running_or_waiting`
- `ready_for_postprocess=false`
- `final=false`
- `completed_cycles=10 / 288`
- `remaining_cycles=278`
- `rows=216`
- `line_count=216`
- `line_count_matches_manifest=true`
- `errors=56`
- `last_write_age_sec≈43`

## Current Gate

Do not run rank/backtest/stress yet. The next gate remains:

- manifest `final=true`;
- `completed_cycles=288`;
- `line_count_matches_manifest=true`;
- then run guarded `funding-postprocess` with persistence, regime, stress, and acceptance thresholds.
