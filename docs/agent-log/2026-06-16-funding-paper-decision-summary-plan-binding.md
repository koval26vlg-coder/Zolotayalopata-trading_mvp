# Funding Paper Decision Summary Plan Binding - 2026-06-16 05:17 local

## Objective
Continue the research-only `trading_mvp` goal toward a viable non-Binance exchange strategy. No live orders, no API keys, no margin/leverage execution, no investment advice.

## Collector Readiness
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Latest strict audit: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_051749.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Status: `running_or_waiting`
- Completed cycles: `93 / 288`
- Progress: `32.29%`
- Rows: `2232`
- Errors: `558`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

## Code Change
Closed a paper-decision summary/plan binding bypass.

Changed behavior:
- `funding_paper_decision_report` now requires the paper-forward summary to include a `plan` path when `plan_path` is provided.
- If missing, it adds `summary_plan_path_missing` and rejects the paper decision.
- If the summary plan path differs from `plan_path`, it adds `summary_plan_path_mismatch` and rejects the paper decision.
- This prevents accepting a forged or detached paper summary with a separately valid plan artifact.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/tests/test_basis.py`

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py` passed.
- Targeted paper-decision binding tests passed: 4 tests OK.
- Full suite passed: `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests` -> 176 tests OK.
- PowerShell syntax parse passed: `PowerShell syntax OK`.

## Next Step
Continue condition-based waiting. When strict audit returns `ready_for_postprocess=true`, run strict `funding-final-review`. The paper-forward decision path now requires plan evidence and summary-plan binding.
