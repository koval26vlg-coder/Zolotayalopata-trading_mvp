# 2026-06-15 Funding Postprocess Preflight

## Purpose

Prevent final funding postprocess from running on a corrupted or partially repaired dataset. `final=true` is necessary but not sufficient: the JSONL line count must match manifest `rows`.

## Implemented

- `run_funding_postprocess_file()` now calls `funding_collect_status()` when `require_final=True`.
- If manifest rows and JSONL line count differ, it returns:
  - `ok=false`
  - `status=line_count_mismatch`
  - `collect_status` with exact counts
- Rank and backtest artifacts are not written in this failure mode.

## Verification

- Added regression: `test_funding_postprocess_blocks_final_manifest_when_line_count_mismatches`.
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 24 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 96 tests ... OK`

## Live Collect Status

Latest `funding-status`:

- `status=running_or_waiting`
- `ready_for_postprocess=false`
- `final=false`
- `completed_cycles=10 / 288`
- `rows=216`
- `line_count=216`
- `line_count_matches_manifest=true`
- `errors=56`
- `last_write_age_sec≈172`
- `stderr=0 bytes`

Current collector processes:

- Parent `pwsh`: PID `19088`
- Python child: PID `22644`
- Python worker child observed: PID `24432`
- Child command line includes `--resume`.

## Next Gate

Continue waiting for:

- `final=true`
- `completed_cycles=288`
- `line_count_matches_manifest=true`

Only then run guarded `funding-postprocess` with persistence, regime, stress, and acceptance thresholds.
