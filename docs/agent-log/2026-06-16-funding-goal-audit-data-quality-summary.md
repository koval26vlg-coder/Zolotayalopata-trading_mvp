# Funding goal-audit data-quality summary

## Goal Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- Current 24h funding collector is still running; final-review/postprocess was not run.

## Collector Check
- Input: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Processes present during check: `14080`, `29320`, `25592`, `8060`.
- Manifest state: `final=false`, `completed_cycles=102`, `cycles=288`, `rows=2448`, `errors=612`.
- Last JSONL write observed: `2026-06-16T06:03:04+03:00`.

## Strict Audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_0615.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Progress: `102 / 288` cycles (`35.42%`)
- Line count: `2448`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Data-quality metrics now surfaced in `summary`:
  - `data_quality_accepted=false`
  - `unique_cycles=102`
  - `avg_rows_per_cycle=24.0`
  - `min_rows_per_cycle=24`
  - `error_rate=0.2`
  - `cycle_market_duplicate_rate=0.0`
  - required fields `spot_bid_qty`, `spot_ask_qty`, `spot_top_min_notional_quote`: `1.0` presence

## Change
- `funding_goal_audit.summary` now includes:
  - `data_quality_accepted`
  - `data_quality_reasons`
  - `data_quality_metrics`
- This does not change gate behavior; it makes readiness evidence explicit at the top-level audit summary.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0.
- Targeted unittest: `test_funding_goal_audit_waits_for_unready_collect`: `1 test OK`.
- Full unittest discover: `187 tests OK`.
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`.
- CLI smoke: `funding-goal-audit -FundingStrictResearch` wrote `funding_goal_audit_partial_20260616_0615.json` with top-level data-quality summary.

## Decision
- Do not run `funding-final-review`, `funding-rank`, or `funding-backtest` yet.
- Continue condition-based readiness checks and run strict final-review only after `ready_for_postprocess=true`.
