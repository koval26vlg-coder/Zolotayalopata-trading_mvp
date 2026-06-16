# Funding final-review metric summary

## Goal Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running; final postprocess/backtest was not run.

## Collector Check
- Input: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Processes present during check: `14080`, `29320`, `25592`, `8060`.
- Manifest state at first check: `final=false`, `completed_cycles=102`, `cycles=288`, `rows=2448`, `errors=612`.
- Strict audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_0620.json`
- Strict audit result: `collecting_funding`, `ready_for_postprocess=false`, blockers `collector_not_ready`, `status_not_final`, `min_completed_cycles`, `min_unique_cycles`.

## Change
- Added top-level final-review metric summary via `_funding_final_review_metric_summary`.
- Completed final-review summaries now surface:
  - backtest sample/economics: `backtest_total_trades`, `backtest_win_rate`, `backtest_expectancy_quote`, `backtest_net_pnl_quote`, `backtest_max_drawdown_quote`, `backtest_profit_factor`;
  - OOS metrics: `oos_accepted`, `oos_train_rows`, `oos_rows`, `oos_net_pnl_quote`, `oos_win_rate`, `oos_expectancy_quote`, `oos_max_drawdown_quote`;
  - walk-forward metrics: `walk_forward_accepted`, `walk_forward_windows`, `walk_forward_accepted_windows`, `walk_forward_avg_test_net_pnl_quote`, `walk_forward_worst_test_net_pnl_quote`;
  - stress/research gate state: `stress_accepted`, `research_acceptance_accepted`, `research_acceptance_reasons`;
  - data quality: `data_quality_accepted`, `data_quality_metrics`.
- Not-ready final-review summaries now also expose collector progress and data-quality reasons.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0.
- Targeted unittest: `test_funding_final_review_blocks_not_final_collect_before_downstream_artifacts` and `test_funding_final_review_writes_regime_report_for_ready_collect`: `2 tests OK`.
- Full unittest discover: `187 tests OK`.
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`.

## CLI Smoke
- Command: `funding-final-review --strict-research` on the current partial 24h collect.
- Output: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_final_review_not_ready_smoke_20260616_0620.json`
- Result: `status=not_ready_for_postprocess`, `ready_for_postprocess=false`, `collector_status=running_or_waiting`, `completed_cycles=103`, `line_count=2472`.
- Data-quality reasons: `min_completed_cycles`, `min_unique_cycles`.
- Downstream smoke artifacts were not created.

## Decision
- Do not run final rank/backtest/decision artifacts yet.
- Continue condition-based readiness checks and run strict final-review only after `ready_for_postprocess=true`.
