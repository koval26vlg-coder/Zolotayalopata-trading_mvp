# 2026-06-16 Funding Goal Audit

## Goal
Add a single research-only audit artifact that reports the current funding strategy stage, blockers, and the next safe action without starting final postprocess, paper-forward, live orders, API keys, leverage, or margin execution.

## Collector Status Before Work
- `funding-status --strict-research`: `ready_for_postprocess=false`
- status: `running_or_waiting`
- cycles: `80 / 288`
- rows: `1920`
- errors: `480`
- error_rate: `0.20`
- readiness blockers: `status_not_final`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Final funding postprocess was not run.

## Code Changes
- Added `funding_goal_audit` in `trading_mvp/src/basis.py`.
- Added `default_funding_goal_audit_path`.
- Added CLI command `funding-goal-audit`.
- Added PowerShell action `funding-goal-audit`.
- Added tests for:
  - unready collector -> `collecting_funding` / `wait_and_recheck`;
  - validated paper-forward decision -> `paper_forward_validated` / `extend_paper_forward_dataset`;
  - CLI parser and strict preset coverage.

## Gate Behavior
The audit reads:
- funding collect JSONL + manifest;
- optional final review artifact;
- optional paper plan;
- optional paper-forward summary;
- optional paper decision report.

Possible stages:
- `collecting_funding`
- `funding_final_review_pending`
- `funding_final_review_invalid`
- `research_rework_required`
- `paper_plan_pending`
- `paper_plan_not_ready`
- `paper_forward_pending`
- `paper_decision_pending`
- `paper_forward_validated`
- `paper_rework_required`

The audit always emits:
- `research_only=true`
- `live_orders=false`
- `api_keys_required=false`
- `leverage_enabled=false`
- `margin_execution=false`

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_goal_audit_waits_for_unready_collect`
  - `test_funding_goal_audit_validates_only_paper_forward_not_live`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite: `python -m unittest discover -s trading_mvp/tests`
  - result: `160 tests OK`.
- PowerShell smoke:
  - action: `funding-goal-audit`
  - output: `exports/trading-mvp/funding/funding_goal_audit_current_20260616.json`
  - stage: `collecting_funding`
  - next_action: `wait_and_recheck`
  - `live_orders=false`

## Current Audit Artifact
- `exports/trading-mvp/funding/funding_goal_audit_current_20260616.json`

## Next Gate
Continue polling with:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 `
  -Action funding-goal-audit `
  -FundingStrictResearch `
  -InputPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl `
  -ManifestPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json
```

When stage moves past `collecting_funding` and `ready_for_postprocess=true`, run `funding-final-review`.
