# Funding paper component economics gate

## Goal Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- Current 24h funding collector is still running; final-review/postprocess was not run.

## Collector Check
- Input: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Processes present during check: `14080`, `29320`, `25592`, `8060`.
- Manifest state: `final=false`, `completed_cycles=104`, `cycles=288`, `rows=2496`, `errors=624`.
- Strict audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_0645.json`
- Strict audit result: `collecting_funding`, `ready_for_postprocess=false`.
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`.

## Change
- Added `FUNDING_PAPER_REQUIRED_METRICS` with aggregate and component economics:
  - `total_trades`, `win_rate`, `expectancy_quote`, `net_pnl_quote`, `max_drawdown_quote`;
  - `funding_pnl_quote`, `basis_pnl_quote`, `fees_quote`, `slippage_quote`.
- `funding_paper_decision_report` now requires component economics and emits them in `summary`.
- `_funding_paper_summary_artifact_gate_reasons` now rejects paper-forward summaries missing component economics.
- `_funding_paper_decision_artifact_gate_reasons` now validates component metrics across decision summary, decision metrics, and paper summary metrics.
- `funding_goal_audit.summary` now surfaces final/paper component economics:
  - `final_funding_pnl_quote`, `final_basis_pnl_quote`, `final_fees_quote`, `final_slippage_quote`;
  - `paper_forward_funding_pnl_quote`, `paper_forward_basis_pnl_quote`, `paper_forward_fees_quote`, `paper_forward_slippage_quote`.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0.
- Targeted unittest: paper decision acceptance, missing required metrics, goal-audit validated paper-forward: `3 tests OK`.
- Full unittest discover: `187 tests OK`.
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`.
- CLI smoke: `funding-goal-audit -FundingStrictResearch` wrote `funding_goal_audit_partial_20260616_0645.json`; component fields are present and `null` because downstream artifacts do not exist yet.

## Decision
- Do not run final rank/backtest/decision artifacts yet.
- Continue condition-based readiness checks and run strict final-review only after `ready_for_postprocess=true`.
