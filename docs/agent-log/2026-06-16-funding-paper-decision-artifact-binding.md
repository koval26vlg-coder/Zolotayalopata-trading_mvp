# Funding paper-decision artifact binding

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess must not run yet.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_052550.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `95 / 288`
- Remaining cycles: `193`
- Progress: `32.99%`
- Rows: `2280`
- Errors: `570`
- Last write: `2026-06-16T05:23:29+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `funding_paper_decision_report` now binds paper-forward summary evidence to the original accepted plan more tightly:
  - summary `frozen_config` must match the plan's effective frozen config;
  - summary `output` must match `plan.paper_output_path` when present;
  - summary `source_input` must match `plan.source_input` when present;
  - summary `input` must not reuse the research source input.
- Added regression tests for frozen-config mismatch and paper-output mismatch.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `3 tests OK`
- Full unittest discover: `178 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict audit says the collector is not ready.
- Continue condition-based readiness checks and run strict final-review only after the collector is final and quality gates pass.
