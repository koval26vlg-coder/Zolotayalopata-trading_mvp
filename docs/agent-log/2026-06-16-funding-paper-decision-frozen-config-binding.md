# Funding paper-decision frozen-config binding

## Context
- Active goal remains research-only: no live orders, no API keys, no leverage/margin execution.
- Current 24h funding collector is not ready for final-review/postprocess.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_052232.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `94 / 288`
- Remaining cycles: `194`
- Progress: `32.64%`
- Rows: `2256`
- Errors: `564`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `funding_paper_decision_report` now rejects paper-forward summaries whose effective `frozen_config` differs from the source paper plan.
- Comparison uses canonical dataclass defaults for `FundingBacktestConfig`, `FundingAcceptanceConfig`, and `FundingStressConfig`, matching how paper-forward execution materializes the plan.
- Added regression test for forged/mismatched summary frozen config.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `2 tests OK`
- Full unittest discover: `177 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict audit says the collector is not ready.
- Continue with condition-based checks until the manifest is final and strict readiness passes.
