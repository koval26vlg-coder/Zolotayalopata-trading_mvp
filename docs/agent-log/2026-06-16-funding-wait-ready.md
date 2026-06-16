# 2026-06-16 Funding Wait Ready

## Goal
Add a condition-based wait helper for the 24h funding collector so the final review is triggered only after `ready_for_postprocess=true`, not after a guessed timer.

## Collector Status Before Work
- goal audit: `collecting_funding`
- `ready_for_postprocess=false`
- cycles: `81 / 288`
- rows: `1944`
- errors: `486`
- blockers: `status_not_final`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Final funding postprocess was not run.

## Code Changes
- Added `wait_funding_ready` in `trading_mvp/src/basis.py`.
- Added `default_funding_wait_ready_path`.
- Added CLI command `funding-wait-ready`.
- Added PowerShell action `funding-wait-ready`.
- Added tests for:
  - immediate ready return on final/strict-ready collect;
  - timeout on unready collect without sleeping;
  - CLI parser and strict preset coverage.

## Behavior
`funding-wait-ready`:
- polls `funding_collect_status`;
- returns `ready_for_postprocess` only when strict readiness passes;
- returns `stale`, `missing_output`, `missing_manifest`, or `timeout` without running downstream;
- writes JSON evidence with final status and bounded history;
- keeps `research_only=true`, `live_orders=false`, `api_keys_required=false`, `leverage_enabled=false`, `margin_execution=false`.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_wait_funding_ready_returns_ready_without_sleep_for_final_collect`
  - `test_wait_funding_ready_times_out_without_ready_collect`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite: `python -m unittest discover -s trading_mvp/tests`
  - result: `162 tests OK`.
- PowerShell smoke:
  - action: `funding-wait-ready`
  - `-Seconds 0`
  - output: `exports/trading-mvp/funding/funding_wait_ready_current_20260616.json`
  - status: `timeout`
  - final_status: `running_or_waiting`
  - cycles: `81 / 288`
  - `live_orders=false`

## Next Gate
Use `funding-wait-ready` for condition-based continuation. When it returns `status=ready_for_postprocess`, run `funding-final-review`.
