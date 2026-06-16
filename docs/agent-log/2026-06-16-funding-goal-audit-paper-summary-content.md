# Funding goal-audit paper-summary content gate

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_055157.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `100 / 288`
- Remaining cycles: `188`
- Progress: `34.72%`
- Rows: `2400`
- Errors: `600`
- Last write: `2026-06-16T05:51:47+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `funding_goal_audit` paper-summary gate now requires the paper-forward summary itself to carry content evidence before moving to paper-decision stage.
- `_funding_paper_summary_artifact_gate_reasons` now validates:
  - required metrics: `total_trades`, `win_rate`, `expectancy_quote`, `net_pnl_quote`, `max_drawdown_quote`;
  - `paper_acceptance.accepted=true`;
  - coverage has `duration_accepted`, `rows_accepted`, and `markets_accepted`.
- Added regression test for a paper summary with missing top-level `metrics`.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `4 tests OK`
- Full unittest discover: `186 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
