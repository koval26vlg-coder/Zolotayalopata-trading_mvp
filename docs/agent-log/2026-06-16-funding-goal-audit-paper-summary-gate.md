# Funding goal-audit paper-summary artifact gate

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_054437.json`
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
- `funding_goal_audit` now validates `paper_summary` before accepting a `paper_decision` artifact.
- Added `_funding_paper_summary_artifact_gate_reasons` with checks for:
  - summary safety invariants: research-only/no-live/no-keys/no-leverage/no-margin;
  - `mode=funding_paper_forward`, `status=completed`, `ok=true`;
  - summary `plan` matches `paper_plan_path`;
  - summary `source_input` matches `paper_plan.source_input`;
  - summary `input` does not reuse the research source input;
  - summary `output` matches `paper_plan.paper_output_path` when present;
  - effective summary `frozen_config` matches effective plan `frozen_config`.
- Added `_paper_forward_summary_fixture` in tests for realistic paper-forward summaries.
- Added regression test for `paper_summary` with `live_orders=true`.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0
- Targeted unittest: `4 tests OK`
- Full unittest discover: `184 tests OK`
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
