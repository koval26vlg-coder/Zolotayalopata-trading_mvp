# Funding goal-audit final-review binding

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_053146.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `96 / 288`
- Remaining cycles: `192`
- Progress: `33.33%`
- Rows: `2304`
- Errors: `576`
- Last write: `2026-06-16T05:29:09+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `funding_goal_audit` now validates that `final_review` belongs to the exact collector input/manifest being audited before advancing to paper-plan/paper-forward stages.
- Added `_funding_final_review_artifact_gate_reasons` with checks for:
  - mode must be `funding_final_review`;
  - final review `input` must match the audited collector input;
  - final review `manifest` must match the audited manifest.
- Existing goal-audit fixtures now use realistic final-review artifacts with `mode`, `input`, and `manifest` fields.
- Added regression test for stale final review that points to a different input path.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `4 tests OK`
- Full unittest discover: `180 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
