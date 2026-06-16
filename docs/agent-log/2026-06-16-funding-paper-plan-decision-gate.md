# Funding Paper Plan Decision Gate - 2026-06-16 05:05 local

## Objective
Continue the research-only `trading_mvp` goal toward a viable non-Binance exchange strategy. No live orders, no API keys, no margin/leverage execution, no investment advice.

## Collector Readiness
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Latest strict audit: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_050536.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Status: `running_or_waiting`
- Completed cycles: `91 / 288`
- Progress: `31.60%`
- Rows: `2184`
- Errors: `546`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

## Code Change
Closed the remaining paper-forward bypass outside `funding-final-review`.

Changed behavior:
- `create_funding_paper_forward_plan_file` now requires an accepted `funding_decision_report` for a ready paper-forward plan.
- Missing decision evidence adds `decision_report_missing` and returns `status=decision_report_required` for accepted postprocess-only research.
- Rejected decision evidence adds `decision_report_not_accepted` plus decision reasons and returns `ready_for_paper_forward=false`.
- `run_funding_research_finalize_file` now defaults `create_paper_plan=false`; if explicitly enabled, it passes/uses `decision_report_path`.
- `funding-paper-plan` CLI now requires `--decision-report`.
- `run_mvp.ps1 -Action funding-paper-plan` now requires `-DecisionReportPath`.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_basis.py`

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py` passed.
- Targeted paper-plan/finalize/CLI tests passed: 6 tests OK.
- Full suite passed: `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests` -> 171 tests OK.
- PowerShell syntax parse passed: `PowerShell syntax OK`.

## Next Step
Continue condition-based waiting. When strict audit reports `ready_for_postprocess=true`, run `funding-final-review`. Paper-forward is now blocked unless final decision accepts postprocess + gate + regime + frontier + sensitivity + OOS + walk-forward + stress evidence.
