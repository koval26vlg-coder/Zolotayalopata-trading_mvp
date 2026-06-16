# Funding goal-audit metric summary

## Goal Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- Current 24h funding collector is still running; final-review/postprocess was not run.

## Collector Check
- Input: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Processes present during check: `14080`, `29320`, `25592`, `8060`.
- Manifest state: `final=false`, `completed_cycles=103`, `cycles=288`, `rows=2472`, `errors=618`.
- Strict audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_0635.json`
- Strict audit result: `collecting_funding`, `ready_for_postprocess=false`.
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`.

## Change
- Added `_funding_goal_audit_metric_summary`.
- `funding_goal_audit.summary` now surfaces final-review, paper-forward, and paper-decision metrics in one top-level audit object.
- New summary fields include:
  - final-review: `final_review_accepted`, `final_review_verdict`, `final_backtest_total_trades`, `final_backtest_win_rate`, `final_backtest_expectancy_quote`, `final_backtest_net_pnl_quote`, `final_backtest_max_drawdown_quote`, `final_oos_accepted`, `final_oos_net_pnl_quote`, `final_walk_forward_accepted`, `final_walk_forward_avg_test_net_pnl_quote`, `final_stress_accepted`;
  - paper-forward: `paper_forward_status`, `paper_forward_total_trades`, `paper_forward_win_rate`, `paper_forward_expectancy_quote`, `paper_forward_net_pnl_quote`, `paper_forward_max_drawdown_quote`, `paper_forward_profit_factor`, `paper_forward_acceptance_accepted`, `paper_forward_coverage`;
  - paper-decision: `paper_decision_accepted`, `paper_decision_verdict`, `paper_decision_next_action`.
- This is additive; gate behavior is unchanged.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0.
- Targeted unittest: `test_funding_goal_audit_validates_only_paper_forward_not_live`: `1 test OK`.
- Full unittest discover: `187 tests OK`.
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`.
- CLI smoke: `funding-goal-audit -FundingStrictResearch` wrote `funding_goal_audit_partial_20260616_0635.json`; final/paper metrics are present and `null` because downstream artifacts do not exist yet.

## Decision
- Do not run `funding-final-review`, `funding-rank`, or `funding-backtest` yet.
- Continue condition-based readiness checks and run strict final-review only after `ready_for_postprocess=true`.
