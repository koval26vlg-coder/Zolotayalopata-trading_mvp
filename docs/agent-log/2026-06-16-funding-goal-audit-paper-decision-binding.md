# Funding goal-audit paper-decision binding

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_052842.json`
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

## Process check
- Metadata: `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-06-15-funding-collect-24h-spotliq-20260615_202709.json`
- Launcher PID `14080`, child PowerShell PID `29320`, Python PIDs `25592` and `8060` were present/responding.
- `stdout` and `stderr` logs exist and are empty.
- Poll interval is `300` seconds, so the current wait is treated as normal, not a stuck process.

## Change
- `funding_goal_audit` now validates that an accepted `paper_decision` artifact belongs to the exact `paper_summary_path` and `paper_plan_path` passed into the audit.
- Added `_funding_paper_decision_artifact_gate_reasons` with checks for:
  - mode must be `funding_paper_decision_report`;
  - decision `summary_path` must match the audited paper summary;
  - decision `plan_path` must match the audited paper plan.
- Added regression test for a paper decision that points to a different summary path.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `3 tests OK`
- Full unittest discover: `179 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
