# Funding Paper Decision Plan Gate - 2026-06-16 05:15 local

## Objective
Continue the research-only `trading_mvp` goal toward a viable non-Binance exchange strategy. No live orders, no API keys, no margin/leverage execution, no investment advice.

## Collector Readiness
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Latest strict audit: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_051518.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Status: `running_or_waiting`
- Completed cycles: `93 / 288`
- Progress: `32.29%`
- Rows: `2232`
- Errors: `558`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

## Code Change
Closed a paper-decision bypass.

Changed behavior:
- `funding_paper_decision_report` now requires plan evidence.
- If `plan_path` is missing, it adds `plan_required` and rejects the paper decision.
- If `plan_path` is provided but invalid/missing, it adds `plan_missing_or_invalid`.
- `funding-paper-decision-report --plan` is now required by the CLI parser.
- `run_mvp.ps1 -Action funding-paper-decision-report` now fails early unless `-FundingPlanPath` is provided.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_basis.py`

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py` passed.
- Targeted paper-decision tests passed: 4 tests OK.
- Full suite passed: `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests` -> 174 tests OK.
- PowerShell syntax parse passed: `PowerShell syntax OK`.

## Next Step
Continue condition-based waiting. When strict audit returns `ready_for_postprocess=true`, run strict `funding-final-review`. Goal completion remains unproven until final review and paper-forward validation pass all gates.
