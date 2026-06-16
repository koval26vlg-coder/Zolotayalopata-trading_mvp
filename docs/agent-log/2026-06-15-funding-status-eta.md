# 2026-06-15 Funding Status ETA

## Purpose

Improve long-running funding collection monitoring while the 24h dataset is still incomplete. The status command now reports estimated cycle interval, next expected cycle time, and ETA so the pipeline can distinguish normal waiting from a stale collector.

## Implemented

- `funding_collect_status()` now returns:
  - `cycle_interval_estimate_sec`
  - `estimated_next_cycle_ts`
  - `estimated_next_cycle_in_sec`
  - `eta_sec`
- Estimate is based on the last two `cycle_summaries[*].ts` values when available.
- Fallback uses `duration_sec / completed_cycles`.

## Verification

- Added regression: `test_funding_collect_status_reports_eta_from_cycle_timestamps`.
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 25 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 97 tests ... OK`

## Live Status

Initial check after implementation:

- `completed_cycles=10 / 288`
- `rows=216`
- `line_count=216`
- `cycle_interval_estimate_sec≈336.30`
- `estimated_next_cycle_in_sec≈23.52`
- `eta_sec≈93490.26`
- `stderr=0 bytes`

Follow-up after waiting:

- `completed_cycles=11 / 288`
- `rows=240`
- `line_count=240`
- `line_count_matches_manifest=true`
- `last_write_age_sec≈29.07`
- `estimated_next_cycle_in_sec≈307.20`
- `eta_sec≈93146.77`
- `ready_for_postprocess=false`

## Gate

Still do not run `funding-postprocess`. Required gate remains:

- `final=true`
- `completed_cycles=288`
- `line_count_matches_manifest=true`
- no stale status
