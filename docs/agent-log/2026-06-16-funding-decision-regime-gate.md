# Funding Decision Regime Gate - 2026-06-16 04:57 local

## Objective
Continue the research-only `trading_mvp` goal toward a viable non-Binance exchange strategy. No live orders, no API keys, no margin/leverage execution, no investment advice.

## Collector Readiness
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Latest strict audit: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_045738.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Status: `running_or_waiting`
- Completed cycles: `90 / 288`
- Progress: `31.25%`
- Rows: `2160`
- Errors: `540`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

## Code Change
Hardened `funding_decision_report` so a positive funding/basis carry verdict now requires explicit regime evidence, not only gate/frontier/sensitivity summaries.

Changed behavior:
- Added `regime_report_path` to `funding_decision_report`.
- Missing regime artifact adds `missing:regime_report`.
- Positive acceptance now requires:
  - `regime_summary.eligible_markets > 0`
  - `regime_summary.liquidity_pass > 0`
  - `regime_summary.economics_pass > 0`
- Decision summary now exposes regime counters and reason counts.
- `funding-final-review` passes the created `regime_report` into `funding_decision_report`.
- CLI now supports `funding-decision-report --regime-report`.
- PowerShell wrapper now supports `-RegimeReportPath` for `funding-decision-report`.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_basis.py`

## Partial Decision Gate Check
Monitoring-only partial artifacts:
- Frontier: `exports/trading-mvp/funding/funding_frontier_report_partial_decision_gate_20260616_0452.json`
- Sensitivity: `exports/trading-mvp/backtests/funding_sensitivity_partial_decision_gate_20260616_0452.json`
- Decision: `exports/trading-mvp/funding/funding_decision_report_partial_decision_gate_20260616_0452.json`

Partial decision result:
- accepted: `false`
- verdict: `wait_for_final_dataset`
- next_action: `wait_and_recheck`
- ready_for_postprocess: `false`
- regime eligible markets: `0`
- regime liquidity pass: `1`
- regime economics pass: `0`
- reasons: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

Partial sensitivity note:
- `funding-sensitivity` on current partial data created an artifact but took long enough that the combined shell command timed out before decision generation.
- Re-running only `funding-decision-report` succeeded.
- No final postprocess was run.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py` passed.
- Targeted tests passed: 3 tests OK.
- Full suite passed: `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests` -> 170 tests OK.
- PowerShell syntax parse passed: `PowerShell syntax OK`.

## Next Step
Continue condition-based waiting. When strict audit returns `ready_for_postprocess=true`, run `funding-final-review` with strict research settings and inspect postprocess/gate/regime/frontier/sensitivity/decision/OOS/walk-forward/stress artifacts. If final still has zero eligible regime/economics markets, do not proceed to paper-forward; narrow universe or shift strategy family.
