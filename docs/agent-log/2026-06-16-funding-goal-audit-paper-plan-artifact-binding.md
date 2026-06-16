# Funding goal-audit paper-plan artifact binding

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_054105.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `98 / 288`
- Remaining cycles: `190`
- Progress: `34.03%`
- Rows: `2352`
- Errors: `588`
- Last write: `2026-06-16T05:40:20+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `funding_goal_audit` now validates that a ready `paper_plan` belongs to the current collector/final-review artifact chain before advancing to paper-forward stages.
- Added `_funding_paper_plan_artifact_gate_reasons` with checks for:
  - plan mode must be `funding_paper_forward_plan`;
  - `plan.source_input` must match the audited collector input;
  - if `final_review.artifact_paths.paper_plan` exists, it must match the provided `paper_plan_path`;
  - if `final_review.artifact_paths.postprocess` exists, it must match `plan.source_postprocess`;
  - if `final_review.artifact_paths.decision_report` exists, it must match `plan.source_decision_report`.
- Updated positive goal-audit fixtures to include realistic `mode` and `source_input` fields.
- Added regression test for a paper plan that points to a different postprocess artifact than the one declared by final-review.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `4 tests OK`
- Full unittest discover: `183 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
