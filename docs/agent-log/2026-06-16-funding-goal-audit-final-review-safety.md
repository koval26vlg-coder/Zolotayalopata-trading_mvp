# Funding goal-audit final-review safety gate

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_053748.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `97 / 288`
- Remaining cycles: `191`
- Progress: `33.68%`
- Rows: `2328`
- Errors: `582`
- Last write: `2026-06-16T05:34:44+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Change
- `run_funding_final_review_file` now writes top-level safety flags to final-review artifacts in both `not_ready_for_postprocess` and completed payloads:
  - `research_only=true`
  - `live_orders=false`
  - `api_keys_required=false`
  - `leverage_enabled=false`
  - `margin_execution=false`
- `funding_goal_audit` now rejects `final_review` artifacts that violate those safety invariants before advancing to paper-plan/paper-forward stages.
- Added regression test for an accepted final-review artifact with `live_orders=true`.
- Added assertion that not-ready final-review output persists the safety flags.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `4 tests OK`
- Full unittest discover: `182 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
