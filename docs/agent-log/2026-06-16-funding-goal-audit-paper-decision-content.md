# Funding goal-audit paper-decision content gate

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_054924.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `99 / 288`
- Remaining cycles: `189`
- Progress: `34.38%`
- Rows: `2376`
- Errors: `594`
- Last write: `2026-06-16T05:45:58+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `funding_goal_audit` now rejects accepted `paper_decision` artifacts that do not carry self-contained decision evidence.
- `_funding_paper_decision_artifact_gate_reasons` now validates:
  - required metrics: `total_trades`, `win_rate`, `expectancy_quote`, `net_pnl_quote`, `max_drawdown_quote`;
  - decision summary metrics match top-level `metrics`;
  - top-level `metrics`, `paper_acceptance`, `coverage`, and `frozen_config` match the audited `paper_summary`;
  - paper acceptance is accepted;
  - coverage has `duration_accepted`, `rows_accepted`, and `markets_accepted`.
- Added `_paper_decision_report_fixture` test helper for realistic paper-decision artifacts.
- Added regression test for forged accepted paper decision with missing top-level metrics.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `4 tests OK`
- Full unittest discover: `185 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
