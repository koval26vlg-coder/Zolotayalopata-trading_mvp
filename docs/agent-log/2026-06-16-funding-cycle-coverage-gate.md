# 2026-06-16 Funding Cycle Coverage Gate

## Goal
Strengthen the funding data-quality gate so final research acceptance requires stable per-cycle market coverage, not only total row count and completed cycle count.

## Collector Status
- status: `running_or_waiting`
- `ready_for_postprocess=false`
- cycles: `83 / 288`
- rows: `1992`
- errors: `498`
- blockers: `status_not_final`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Final postprocess was not run.

## Code Changes
- Added `FundingDataQualityConfig.min_avg_rows_per_cycle`.
- Added `FundingDataQualityConfig.min_min_rows_per_cycle`.
- Added data-quality metrics:
  - `avg_rows_per_cycle`
  - `min_rows_per_cycle`
- Added rejection reasons:
  - `min_avg_rows_per_cycle`
  - `min_min_rows_per_cycle`
- Added CLI/PowerShell quality flags:
  - `--quality-min-avg-rows-per-cycle`
  - `--quality-min-min-rows-per-cycle`
  - `-FundingQualityMinAvgRowsPerCycle`
  - `-FundingQualityMinMinRowsPerCycle`
- Strict research preset now requires:
  - `quality_min_avg_rows_per_cycle=20.0`
  - `quality_min_min_rows_per_cycle=20`

## Current Dataset Under New Gate
Artifact:
- `exports/trading-mvp/funding/funding_goal_audit_coverage_gate_20260616.json`

Metrics:
- rows: `1992`
- completed_cycles: `83`
- unique_cycles: `83`
- avg_rows_per_cycle: `24.0`
- min_rows_per_cycle: `24`
- error_rate: `0.20`
- cycle_market_duplicate_rate: `0.0`
- data-quality reasons: `min_completed_cycles`, `min_unique_cycles`

Interpretation:
- The current collector passes the new per-cycle coverage density threshold.
- It still cannot be postprocessed because the 24h sample is incomplete.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_collect_status_reports_strict_readiness_quality_reasons`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite:
  - `python -m unittest discover -s trading_mvp/tests`
  - result: `162 tests OK`.

## Next Gate
Continue condition-based waiting. When `ready_for_postprocess=true`, run `funding-final-review` with strict research settings.
