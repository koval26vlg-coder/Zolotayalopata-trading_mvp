# Funding Final Review Regime Evidence - 2026-06-16

## Objective
Continue the research-only trading_mvp goal while the 24h funding collector is still running. No live orders, no API keys, no investment advice.

## Collector Status Checked
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Latest audit artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_044546.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `88`
- Rows: `2112`
- Errors: `528`
- Blocking reasons: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Last write observed: `2026-06-16 04:44:15 local`

## Engineering Change
Added a dedicated `regime_report` artifact to `funding-final-review` so final decisions include explicit per-market evidence for:
- funding persistence;
- regime observations;
- spot/perp liquidity;
- economics blockers.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_basis.py`

## Behavior
- If collect is not ready, final-review still writes only the review payload and does not create downstream artifacts, including `regime_report`.
- If collect is ready, final-review creates `regime_report`, includes it in `artifact_paths` and `artifacts_created`, and exposes regime summary counters in final review summary.
- CLI now supports `--regime-report-output`.
- PowerShell wrapper now supports `-RegimeReportPath`.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py` passed.
- Targeted tests passed: 3 tests OK.
- Full suite passed: `python -m unittest discover -s trading_mvp/tests` -> 169 tests OK.
- PowerShell syntax parse passed: `PowerShell syntax OK`.

## Next Step
Continue waiting on condition, not timer guessing. When manifest reaches `final=true` and strict readiness passes, run `funding-final-review` with strict research settings and inspect postprocess, gate, regime, frontier, sensitivity, decision, OOS, walk-forward, stress, and paper-plan artifacts.
